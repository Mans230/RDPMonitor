package io.github.mans230.rdpmonitor.core.security

import android.content.Context
import android.content.MutableContextWrapper
import androidx.credentials.*
import com.google.android.libraries.identity.googleid.GetSignInWithGoogleOption
import com.google.android.libraries.identity.googleid.GoogleIdTokenCredential
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.*
import okhttp3.OkHttpClient
import okhttp3.Request
import java.math.BigInteger
import java.security.KeyFactory
import java.security.SecureRandom
import java.security.Signature
import java.security.spec.RSAPublicKeySpec
import java.util.Base64
import java.util.concurrent.TimeUnit

data class GoogleProfile(val subject: String, val email: String, val name: String)

/** A local app identity only. Google identity never authorizes a server API or replaces PKCE. */
object GoogleIdentity {
    private val http = OkHttpClient.Builder().followRedirects(false).callTimeout(15, TimeUnit.SECONDS).build()
    suspend fun signIn(activity: Context, clientId: String): GoogleProfile {
        require(clientId.endsWith(".apps.googleusercontent.com")) { "Google sign-in needs the app's OAuth client ID configured." }
        val nonce = Base64.getUrlEncoder().withoutPadding().encodeToString(ByteArray(32).also { SecureRandom().nextBytes(it) })
        val option = GetSignInWithGoogleOption.Builder(clientId).setNonce(nonce).build()
        val result = CredentialManager.create(activity).getCredential(MutableContextWrapper(activity), GetCredentialRequest(listOf(option)))
        val credential = result.credential
        require(credential is CustomCredential && credential.type == GoogleIdTokenCredential.TYPE_GOOGLE_ID_TOKEN_CREDENTIAL) { "Google did not return a supported sign-in credential." }
        val token = GoogleIdTokenCredential.createFrom(credential.data).idToken
        return withContext(Dispatchers.IO) {
            val keys = http.newCall(Request.Builder().url("https://www.googleapis.com/oauth2/v3/certs").build()).execute().use { response ->
                require(response.isSuccessful) { "Could not verify Google sign-in. Try again." }
                val bytes = response.body?.byteStream()?.use { input ->
                    val buffer = ByteArray(65537); var size = 0
                    while (size < buffer.size) { val count = input.read(buffer, size, buffer.size - size); if (count < 0) break; size += count }
                    require(size <= 65536); buffer.copyOf(size)
                } ?: error("Google verification is unavailable.")
                Json.parseToJsonElement(bytes.toString(Charsets.UTF_8)).jsonObject
            }
            verify(token, keys, clientId, nonce, System.currentTimeMillis() / 1000)
        }
    }
    suspend fun clear(context: Context) { CredentialManager.create(context).clearCredentialState(ClearCredentialStateRequest()) }

    internal fun verify(token: String, keys: JsonObject, clientId: String, nonce: String, now: Long): GoogleProfile {
        require(token.length in 1..32768)
        val parts = token.split('.'); require(parts.size == 3)
        fun decode(value: String) = Base64.getUrlDecoder().decode(value)
        val header = Json.parseToJsonElement(decode(parts[0]).toString(Charsets.UTF_8)).jsonObject
        fun JsonObject.text(key: String) = (get(key) as? JsonPrimitive)?.contentOrNull
        require(header.text("alg") == "RS256")
        val kid = header.text("kid") ?: error("Missing Google verification key.")
        val key = (keys["keys"] as? JsonArray)?.mapNotNull { it as? JsonObject }?.singleOrNull { it.text("kid") == kid } ?: error("Google verification key has changed. Try again.")
        require(key.text("kty") == "RSA" && key.text("alg") in listOf(null, "RS256") && key.text("use") in listOf(null, "sig"))
        val modulus = BigInteger(1, decode(key.text("n") ?: error("Missing key")))
        require(modulus.bitLength() >= 2048)
        val publicKey = KeyFactory.getInstance("RSA").generatePublic(RSAPublicKeySpec(modulus, BigInteger(1, decode(key.text("e") ?: error("Missing exponent")))))
        require(Signature.getInstance("SHA256withRSA").run { initVerify(publicKey); update("${parts[0]}.${parts[1]}".toByteArray(Charsets.US_ASCII)); verify(decode(parts[2])) })
        val claims = Json.parseToJsonElement(decode(parts[1]).toString(Charsets.UTF_8)).jsonObject
        require(claims.text("iss") in setOf("accounts.google.com", "https://accounts.google.com"))
        require(claims.text("aud") == clientId)
        require(claims.text("nonce") == nonce)
        val exp = claims["exp"]?.jsonPrimitive?.longOrNull ?: error("Missing expiry")
        val issued = claims["iat"]?.jsonPrimitive?.longOrNull ?: error("Missing issuance time")
        require(exp > now && issued <= now + 300 && issued <= exp)
        require(claims["email_verified"]?.jsonPrimitive?.booleanOrNull == true)
        val subject = claims.text("sub")?.takeIf { it.length in 1..255 } ?: error("Missing identity")
        val email = claims.text("email")?.takeIf { it.length in 3..320 } ?: error("Missing email")
        return GoogleProfile(subject, email, (claims.text("name") ?: email).take(120))
    }
}
