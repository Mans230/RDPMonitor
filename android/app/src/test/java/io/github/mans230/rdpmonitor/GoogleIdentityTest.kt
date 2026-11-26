package io.github.mans230.rdpmonitor

import io.github.mans230.rdpmonitor.core.security.GoogleIdentity
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test
import java.security.KeyPairGenerator
import java.security.Signature
import java.security.interfaces.RSAPublicKey
import java.util.Base64

class GoogleIdentityTest {
    companion object {
        private val pair = KeyPairGenerator.getInstance("RSA").apply { initialize(2048) }.generateKeyPair()
        private val publicKey = pair.public as RSAPublicKey
        private const val client = "fixture.apps.googleusercontent.com"
        private val encoder = Base64.getUrlEncoder().withoutPadding()
        private fun encode(data: ByteArray) = encoder.encodeToString(data)
        private val keys = buildJsonObject { put("keys", buildJsonArray { add(buildJsonObject {
            put("kid", "fixture"); put("kty", "RSA"); put("alg", "RS256")
            put("n", encode(publicKey.modulus.toByteArray())); put("e", encode(publicKey.publicExponent.toByteArray()))
        }) }) }
    }
    private fun token(overrides: Map<String, JsonElement> = emptyMap(), algorithm: String = "RS256"): String {
        val header = encode("""{"alg":"$algorithm","kid":"fixture"}""".toByteArray())
        val payload = buildJsonObject {
            put("iss", "https://accounts.google.com"); put("aud", client); put("nonce", "one-use-nonce")
            put("iat", 900); put("exp", 1100); put("sub", "stable-google-subject")
            put("email", "fixture@example.test"); put("email_verified", true); put("name", "Test account")
        }.toMutableMap().apply { putAll(overrides) }
        val data = "$header.${encode(JsonObject(payload).toString().toByteArray())}"
        return "$data.${encode(Signature.getInstance("SHA256withRSA").run { initSign(pair.private); update(data.toByteArray()); sign() })}"
    }
    @Test fun verifiedIdentityUsesStableSubjectAndDoesNotReturnBearerTokens() {
        val profile = GoogleIdentity.verify(token(), keys, client, "one-use-nonce", 1000)
        assertEquals("stable-google-subject", profile.subject); assertEquals("fixture@example.test", profile.email)
        assertFalse(profile.toString().contains(token()))
    }
    @Test fun rejectReplayWrongAudienceIssuerExpiryAndUnverifiedEmail() {
        listOf(
            "nonce" to JsonPrimitive("other-nonce"), "aud" to JsonPrimitive("other.apps.googleusercontent.com"),
            "iss" to JsonPrimitive("https://evil.test"), "exp" to JsonPrimitive(999),
            "iat" to JsonPrimitive(2000), "email_verified" to JsonPrimitive(false), "sub" to JsonPrimitive("")
        ).forEach { (key, value) -> assertTrue(key, runCatching { GoogleIdentity.verify(token(mapOf(key to value)), keys, client, "one-use-nonce", 1000) }.isFailure) }
    }
    @Test fun rejectModifiedSignaturesUnknownKeysAndAlgorithmConfusion() {
        val good = token(); val parts = good.split('.')
        val alteredSignature = Base64.getUrlDecoder().decode(parts[2]).apply { this[0] = (this[0].toInt() xor 1).toByte() }
        val altered = "${parts[0]}.${parts[1]}.${encoder.encodeToString(alteredSignature)}"
        assertTrue(runCatching { GoogleIdentity.verify(altered, keys, client, "one-use-nonce", 1000) }.isFailure)
        assertTrue(runCatching { GoogleIdentity.verify(token(algorithm = "none"), keys, client, "one-use-nonce", 1000) }.isFailure)
        assertTrue(runCatching { GoogleIdentity.verify(good, buildJsonObject { put("keys", buildJsonArray {}) }, client, "one-use-nonce", 1000) }.isFailure)
    }
}
