package io.github.mans230.rdpmonitor.core.network

import io.github.mans230.rdpmonitor.core.model.*
import io.github.mans230.rdpmonitor.core.security.*
import io.github.mans230.rdpmonitor.data.SnapshotDecoder
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.*
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.ByteArrayOutputStream
import java.util.concurrent.TimeUnit

data class ServerHealth(val pairingAvailable: Boolean)
data class PairingLaunch(val pending: PendingPairing, val url: String)

class PanelApi(private val client: OkHttpClient = OkHttpClient.Builder()
    .followRedirects(false).followSslRedirects(false).readTimeout(330, TimeUnit.SECONDS).callTimeout(15, TimeUnit.SECONDS).build()) {
    private data class Reply(val status: Int, val body: String, val cookies: List<String>)
    private fun request(origin: String, path: String, body: JsonObject? = null, session: AppSession? = null): Reply {
        val canonical = PrivateOrigin.parse(origin)
        require(path.startsWith("/api/") || path == "/health")
        if (session != null) require(session.origin == canonical && session.expiresAt > System.currentTimeMillis()) { "Sign in again." }
        val request = Request.Builder().url(canonical + path).header("Accept", "application/json")
            .header("User-Agent", "RDPMonitor-Android/0.1")
        session?.let { request.header("Cookie", it.cookie) }
        body?.let {
            request.header("Origin", canonical)
            session?.let { active -> request.header("X-CSRF-Token", active.csrf) }
            request.post(it.toString().toRequestBody("application/json".toMediaType()))
        }
        val call = client.newCall(request.build())
        if (path == "/api/action") {
            call.timeout().timeout(330, TimeUnit.SECONDS)
        } else if (path.startsWith("/api/diag") || path == "/api/setup") {
            call.timeout().timeout(180, TimeUnit.SECONDS)
        }
        return call.execute().use { response ->
            val output = ByteArrayOutputStream()
            response.body?.byteStream()?.use { stream ->
                val buffer = ByteArray(4096)
                while (true) {
                    val count = stream.read(buffer)
                    if (count < 0) { break }
                    require(output.size() + count <= 2 * 1024 * 1024) { "Server response is too large." }
                    output.write(buffer, 0, count)
                }
            }
            Reply(response.code, output.toString("UTF-8"), response.headers.values("Set-Cookie"))
        }
    }
    private suspend fun <T> safe(block: () -> DataResult<T>): DataResult<T> = withContext(Dispatchers.IO) {
        try { block() } catch (e: Exception) {
            when (e) {
                is kotlinx.coroutines.CancellationException -> throw e
                is java.net.UnknownHostException, is java.net.ConnectException, is java.net.SocketTimeoutException ->
                    DataResult.Failed("Cannot reach this server. Connect Tailscale on this device and check the private address.")
                is javax.net.ssl.SSLException -> DataResult.Failed("The HTTPS certificate could not be verified. Check the server address and device time.")
                else -> DataResult.Failed("The server request could not be completed. Check the connection and retry.")
            }
        }
    }
    suspend fun health(profile: ServerProfile): DataResult<ServerHealth> = safe {
        val reply = request(profile.origin, "/health")
        val json = runCatching { Json.parseToJsonElement(reply.body).jsonObject }.getOrNull()
        if (reply.status != 200 || json?.get("ok")?.jsonPrimitive?.booleanOrNull != true || json["auth"]?.jsonPrimitive?.content != "passkey")
            DataResult.Failed("This address did not return a healthy Passkey-enabled RDPMonitor panel.")
        else DataResult.Ready(ServerHealth(json["mobile_pairing"]?.jsonPrimitive?.booleanOrNull == true))
    }
    /** Opt-in server bridge. Older servers return PairingUnavailable, never fake success. */
    suspend fun beginPairing(profile: ServerProfile, scope: String): DataResult<PairingLaunch> = safe {
        require(scope in setOf("monitoring:read", "administration"))
        val pending = BrowserPairing.create(profile.id, profile.origin, System.currentTimeMillis()).copy(scope = scope)
        val reply = request(profile.origin, "/api/mobile/v1/pairings", buildJsonObject {
            put("code_challenge", BrowserPairing.challenge(pending.verifier)); put("code_challenge_method", "S256")
            put("state", pending.state); put("redirect_uri", BrowserPairing.REDIRECT)
            put("scope", pending.scope)
        })
        if (reply.status == 404 || reply.status == 501) DataResult.PairingUnavailable
        else if (reply.status == 200 || reply.status == 201) {
            val data = Json.parseToJsonElement(reply.body).jsonObject
            val url = data.getValue("authorization_url").jsonPrimitive.content
            require(data["confirmation_code"]?.jsonPrimitive?.content == BrowserPairing.matchCode(BrowserPairing.challenge(pending.verifier)))
            DataResult.Ready(PairingLaunch(pending, PrivateOrigin.sameServerUrl(profile.origin, url)))
        } else DataResult.Failed("The server could not start app sign-in. Retry later.")
    }
    suspend fun exchange(callback: PairingCallback): DataResult<AppSession> = safe {
        val pending = callback.pending
        val reply = request(pending.origin, "/api/mobile/v1/exchange", buildJsonObject {
            put("code", callback.code); put("code_verifier", pending.verifier); put("redirect_uri", BrowserPairing.REDIRECT)
        })
        if (reply.status != 200) DataResult.Failed("App sign-in was rejected or expired. Start again.")
        else {
            val data = Json.parseToJsonElement(reply.body).jsonObject
            require(data["scope"]?.jsonPrimitive?.content == pending.scope) { "Approved session permissions did not match" }
            val cookie = reply.cookies.firstOrNull {
                it.startsWith("rdpwc_session=") && it.contains("; Secure", true) && it.contains("; HttpOnly", true)
            }?.substringBefore(';') ?: error("Secure session cookie missing")
            val seconds = data["idle_timeout_seconds"]?.jsonPrimitive?.intOrNull?.coerceIn(60, 1800) ?: 1800
            val csrf = data["csrf"]?.jsonPrimitive?.content?.takeIf { it.length in 16..256 } ?: error("CSRF missing")
            DataResult.Ready(AppSession(pending.profileId, pending.origin, cookie, csrf,
                data["actor"]?.jsonPrimitive?.content ?: "Signed in", System.currentTimeMillis() + seconds * 1000L, seconds, pending.scope))
        }
    }
    suspend fun snapshot(profile: ServerProfile, session: AppSession): DataResult<Snapshot> = safe {
        val reply = request(profile.origin, "/api/stats", session = session)
        when (reply.status) {
            401, 403 -> DataResult.SignInRequired
            200 -> {
                val snapshot = SnapshotDecoder.decode(reply.body)
                val history = runCatching { request(profile.origin, "/api/history", session = session) }.getOrNull()
                DataResult.Ready(if (history?.status == 200)
                    runCatching { SnapshotDecoder.withHistory(snapshot, history.body) }.getOrDefault(snapshot) else snapshot)
            }
            else -> DataResult.Failed("Monitoring could not be refreshed. Previous readings have been retained.")
        }
    }
    suspend fun logout(profile: ServerProfile, session: AppSession): DataResult<Unit> = safe {
        val reply = request(profile.origin, "/api/logout", buildJsonObject {}, session)
        if (reply.status in listOf(200, 401)) DataResult.Ready(Unit)
        else DataResult.Failed("Server sign-out failed. You can revoke this app session in the web panel.")
    }
    suspend fun document(profile: ServerProfile, session: AppSession, path: String): DataResult<JsonElement> = safe {
        val reply = request(profile.origin, path, session = session)
        when (reply.status) {
            401 -> DataResult.SignInRequired
            200 -> DataResult.Ready(Json.parseToJsonElement(reply.body))
            else -> DataResult.Failed(runCatching { Json.parseToJsonElement(reply.body).jsonObject["error"]?.jsonPrimitive?.content }.getOrNull()
                ?: "Server could not load this section (${reply.status}). Retry.")
        }
    }
    suspend fun action(profile: ServerProfile, session: AppSession, body: JsonObject): DataResult<JsonObject> = safe {
        val path = if (body["action"]?.jsonPrimitive?.content == "mobile_revoke") "/api/mobile/v1/revoke" else "/api/action"
        val reply = request(profile.origin, path, body, session)
        val data = runCatching { Json.parseToJsonElement(reply.body).jsonObject }.getOrDefault(JsonObject(emptyMap()))
        if (reply.status == 401) DataResult.SignInRequired
        else if (reply.status == 200 && data["ok"]?.jsonPrimitive?.booleanOrNull != false) DataResult.Ready(data)
        else DataResult.Failed(data["error"]?.jsonPrimitive?.content ?: data["out"]?.toString() ?: "Action failed (${reply.status}). Nothing is assumed to have succeeded.")
    }
}
