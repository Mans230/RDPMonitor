package io.github.mans230.rdpmonitor.core.security

import kotlinx.serialization.Serializable
import java.net.URI
import java.net.URLDecoder
import java.nio.charset.StandardCharsets
import java.security.MessageDigest
import java.security.SecureRandom
import java.util.Base64

@Serializable
data class PendingPairing(val profileId: String, val origin: String, val verifier: String,
                          val state: String, val createdAt: Long)
data class PairingCallback(val code: String, val pending: PendingPairing)

/** A code handoff contract, not an OAuth authorization server implementation. */
object BrowserPairing {
    const val REDIRECT = "io.github.mans230.rdpmonitor://auth/callback"
    private fun random() = ByteArray(32).also(SecureRandom()::nextBytes).let {
        Base64.getUrlEncoder().withoutPadding().encodeToString(it)
    }
    fun create(profileId: String, origin: String, now: Long) =
        PendingPairing(profileId, PrivateOrigin.parse(origin), random(), random(), now)
    fun challenge(verifier: String): String = Base64.getUrlEncoder().withoutPadding()
        .encodeToString(MessageDigest.getInstance("SHA-256").digest(verifier.toByteArray(StandardCharsets.US_ASCII)))
    fun matchCode(challenge: String): String {
        val hex = MessageDigest.getInstance("SHA-256").digest(challenge.toByteArray(StandardCharsets.US_ASCII))
            .take(4).joinToString("") { "%02X".format(it.toInt() and 255) }
        return hex.take(4) + "-" + hex.drop(4)
    }

    fun callback(input: String, pending: PendingPairing?, now: Long): PairingCallback {
        requireNotNull(pending) { "No app sign-in is in progress. Start from Connect server." }
        require(now >= pending.createdAt && now - pending.createdAt <= 10 * 60_000) { "App sign-in expired. Start again." }
        val uri = URI(input)
        require(uri.scheme == "io.github.mans230.rdpmonitor" && uri.host == "auth" && uri.path == "/callback"
            && uri.port == -1 && uri.rawUserInfo == null && uri.rawFragment == null) { "Invalid app sign-in return address." }
        val values = (uri.rawQuery ?: "").split('&').map {
            val pair = it.split('=', limit = 2)
            require(pair.size == 2) { "Invalid app sign-in response." }
            URLDecoder.decode(pair[0], "UTF-8") to URLDecoder.decode(pair[1], "UTF-8")
        }
        require(values.map { it.first }.toSet().size == values.size) { "Duplicate sign-in parameters." }
        val query = values.toMap()
        require(query.keys == setOf("state", "code")) { "Incomplete app sign-in response." }
        require(MessageDigest.isEqual(query.getValue("state").toByteArray(), pending.state.toByteArray())) { "App sign-in did not match this request." }
        val code = query.getValue("code")
        require(code.matches(Regex("[A-Za-z0-9_-]{20,256}"))) { "Invalid authorization code." }
        return PairingCallback(code, pending)
    }
}
