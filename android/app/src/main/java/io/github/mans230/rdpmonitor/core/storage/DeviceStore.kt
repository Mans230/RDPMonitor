package io.github.mans230.rdpmonitor.core.storage

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import io.github.mans230.rdpmonitor.core.model.AppSession
import io.github.mans230.rdpmonitor.core.model.ServerProfile
import io.github.mans230.rdpmonitor.core.security.PendingPairing
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

class DeviceStore(context: Context) {
    private val profiles = context.getSharedPreferences("server_profiles", Context.MODE_PRIVATE)
    private val secrets = context.getSharedPreferences("encrypted_sessions", Context.MODE_PRIVATE)
    private val json = Json { ignoreUnknownKeys = true }
    private val alias = "rdpmonitor.device-session.v1"
    private fun key(): SecretKey {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (store.getKey(alias, null) as? SecretKey)?.let { return it }
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").apply {
            init(KeyGenParameterSpec.Builder(alias, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setKeySize(256).setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build())
        }.generateKey()
    }
    private fun put(name: String, value: String?) {
        if (value == null) { secrets.edit().remove(name).commit(); return }
        val cipher = Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.ENCRYPT_MODE, key()); updateAAD(name.toByteArray()) }
        val bytes = cipher.iv + cipher.doFinal(value.toByteArray(Charsets.UTF_8))
        secrets.edit().putString(name, Base64.encodeToString(bytes, Base64.NO_WRAP)).commit()
    }
    private fun get(name: String): String? = runCatching {
        val encoded = secrets.getString(name, null) ?: return null
        val data = Base64.decode(encoded, Base64.NO_WRAP)
        require(data.size > 28)
        val cipher = Cipher.getInstance("AES/GCM/NoPadding").apply {
            init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, data.copyOfRange(0, 12)))
            updateAAD(name.toByteArray())
        }
        cipher.doFinal(data.copyOfRange(12, data.size)).toString(Charsets.UTF_8)
    }.getOrElse { secrets.edit().remove(name).commit(); null }

    fun profiles(): List<ServerProfile> = runCatching {
        json.decodeFromString<List<ServerProfile>>(profiles.getString("servers", "[]")!!)
    }.getOrDefault(emptyList())
    fun save(profile: ServerProfile) {
        val list = profiles().filterNot { it.id == profile.id || it.origin == profile.origin } + profile
        profiles.edit().putString("servers", json.encodeToString(list)).commit()
    }
    fun remove(id: String) {
        profiles.edit().putString("servers", json.encodeToString(profiles().filterNot { it.id == id })).commit()
        put("session:$id", null)
    }
    fun session(id: String): AppSession? = get("session:$id")?.let { runCatching { json.decodeFromString<AppSession>(it) }.getOrNull() }
    fun session(value: AppSession) = put("session:${value.profileId}", json.encodeToString(value))
    fun clearSession(id: String) = put("session:$id", null)
    fun pending(): PendingPairing? = get("pending")?.let { runCatching { json.decodeFromString<PendingPairing>(it) }.getOrNull() }
    fun pending(value: PendingPairing?) = put("pending", value?.let { json.encodeToString(it) })
}
