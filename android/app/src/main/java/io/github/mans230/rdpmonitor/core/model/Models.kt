package io.github.mans230.rdpmonitor.core.model

import kotlinx.serialization.Serializable
import java.util.UUID

@Serializable
data class ServerProfile(val id: String = UUID.randomUUID().toString(), val name: String, val origin: String)

@Serializable
data class AppSession(val profileId: String, val origin: String, val cookie: String, val csrf: String,
                      val actor: String, val expiresAt: Long, val idleSeconds: Int = 1800,
                      val scope: String = "monitoring:read")

data class ResourcePoint(val secondsAgo: Int, val cpu: Double?, val ram: Double?)
data class ProcessRow(val pid: Int, val name: String, val cpu: Double?, val memoryBytes: Long?)
data class DiskRow(val name: String, val usedPercent: Double?, val freeBytes: Long?)
data class Incident(val title: String, val detail: String, val age: String, val needsAttention: Boolean = false)
data class Snapshot(val host: String, val cpu: Double?, val ram: Double?, val ramUsed: Long?, val ramTotal: Long?,
                    val downloadBps: Double?, val uploadBps: Double?, val sessions: Int?, val disks: List<DiskRow>,
                    val processes: List<ProcessRow>, val history: List<ResourcePoint>, val capturedAt: Long)
data class TrafficDay(val label: String, val downloadBytes: Long, val uploadBytes: Long) {
    val totalBytes get() = downloadBytes + uploadBytes
}
data class Traffic(val days: List<TrafficDay>, val quotaBytes: Long?, val cycleStart: String? = null,
                   val cycleEnd: String? = null, val scope: String? = null) {
    private val billingDays get() = days.filter { (cycleStart == null || it.label >= cycleStart) && (cycleEnd == null || it.label < cycleEnd) }
    val downloadBytes get() = billingDays.sumOf { it.downloadBytes }
    val uploadBytes get() = billingDays.sumOf { it.uploadBytes }
    val totalBytes get() = downloadBytes + uploadBytes
    val quotaFraction get() = quotaBytes?.takeIf { it > 0 }?.let { totalBytes.toDouble() / it }
}

sealed interface DataResult<out T> {
    data class Ready<T>(val value: T): DataResult<T>
    data object SignInRequired: DataResult<Nothing>
    data object PairingUnavailable: DataResult<Nothing>
    data class Failed(val message: String): DataResult<Nothing>
}
