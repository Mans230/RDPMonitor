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
    .followRedirects(false).followSslRedirects(false).callTimeout(15, TimeUnit.SECONDS).build()) {
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
        return client.newCall(request.build()).execute().use { response ->
            val output = ByteArrayOutputStream()
            response.body?.byteStream()?.use { stream ->
                val buffer = ByteArray(4096)
                while (true) {
                    val count = stream.read(buffer)
                    if (count < 0) break
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
    /** Proposed server bridge. A v76/v78 server returns PairingUnavailable, never fake success. */
    suspend fun beginPairing(profile: ServerProfile): DataResult<PairingLaunch> = safe {
        val pending = BrowserPairing.create(profile.id, profile.origin, System.currentTimeMillis())
        val reply = request(profile.origin, "/api/mobile/v1/pairings", buildJsonObject {
            put("code_challenge", BrowserPairing.challenge(pending.verifier)); put("code_challenge_method", "S256")
            put("state", pending.state); put("redirect_uri", BrowserPairing.REDIRECT)
        })
        if (reply.status == 404 || reply.status == 501) DataResult.PairingUnavailable
        else if (reply.status == 200 || reply.status == 201) {
            val url = Json.parseToJsonElement(reply.body).jsonObject.getValue("authorization_url").jsonPrimitive.content
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
            val cookie = reply.cookies.firstOrNull {
                it.startsWith("rdpwc_session=") && it.contains("; Secure", true) && it.contains("; HttpOnly", true)
            }?.substringBefore(';') ?: error("Secure session cookie missing")
            val seconds = data["idle_timeout_seconds"]?.jsonPrimitive?.intOrNull?.coerceIn(60, 1800) ?: 1800
            val csrf = data["csrf"]?.jsonPrimitive?.content?.takeIf { it.length in 16..256 } ?: error("CSRF missing")
            DataResult.Ready(AppSession(pending.profileId, pending.origin, cookie, csrf,
                data["actor"]?.jsonPrimitive?.content ?: "Signed in", System.currentTimeMillis() + seconds * 1000L, seconds))
        }
    }
    suspend fun snapshot(profile: ServerProfile, session: AppSession): DataResult<Snapshot> = safe {
        val reply = request(profile.origin, "/api/stats", session = session)
        when (reply.status) {
            401, 403 -> DataResult.SignInRequired
            200 -> DataResult.Ready(SnapshotDecoder.decode(reply.body))
            else -> DataResult.Failed("Monitoring could not be refreshed. Previous readings have been retained.")
        }
    }
}
