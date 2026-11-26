package io.github.mans230.rdpmonitor.feature.more

import kotlinx.serialization.json.*
import java.text.DateFormat
import java.util.Date
import java.util.Locale

internal fun JsonElement?.obj() = this as? JsonObject
internal fun JsonElement?.rows(): List<JsonObject>? {
    val array = this as? JsonArray ?: return null
    return if (array.all { it is JsonObject }) array.map { it as JsonObject } else null
}
internal fun JsonObject?.text(key: String) = (this?.get(key) as? JsonPrimitive)?.contentOrNull
internal fun JsonObject?.flag(key: String) = (this?.get(key) as? JsonPrimitive)?.booleanOrNull
internal fun JsonObject?.count(key: String) = (this?.get(key) as? JsonPrimitive)?.longOrNull?.takeIf { it >= 0 }
internal fun JsonObject?.number(key: String) = (this?.get(key) as? JsonPrimitive)?.doubleOrNull?.takeIf { it.isFinite() && it >= 0 }
internal fun shown(value: String?) = value?.takeIf { it.isNotBlank() } ?: "Unavailable"
internal fun yesNo(value: Boolean?) = when (value) { true -> "Enabled"; false -> "Disabled"; null -> "Unavailable" }
internal fun words(value: String?) = shown(value?.replace('_', ' ')?.replaceFirstChar { it.uppercase() })
fun detailBytes(value: Long?): String {
    if (value == null || value < 0) return "Unavailable"
    var amount = value.toDouble(); var unit = 0
    val units = listOf("bytes", "KiB", "MiB", "GiB", "TiB", "PiB")
    while (amount >= 1024 && unit < units.lastIndex) { amount /= 1024; unit++ }
    return String.format(Locale.US, if (amount % 1.0 == 0.0) "%.0f %s" else "%.1f %s", amount, if (value == 1L) "byte" else units[unit])
}
fun deviceTimestamp(value: JsonElement?): String {
    val seconds = (value as? JsonPrimitive)?.doubleOrNull?.takeIf { it.isFinite() && it >= 0 && it < 253402300800 } ?: return "Unavailable"
    return DateFormat.getDateTimeInstance(DateFormat.MEDIUM, DateFormat.SHORT).format(Date((seconds * 1000).toLong())) + " · device time"
}
internal fun windowsLogon(value: JsonElement?): String {
    val text = (value as? JsonPrimitive)?.contentOrNull ?: return "Unavailable"
    val milliseconds = Regex("/Date\\((-?\\d+)(?:[+-]\\d{4})?\\)/").matchEntire(text)?.groupValues?.get(1)?.toLongOrNull()
    val instant = runCatching { java.time.Instant.parse(text) }.getOrNull()
    val date = milliseconds?.let(::Date) ?: instant?.let { Date.from(it) }
    return if (date != null) DateFormat.getDateTimeInstance(DateFormat.MEDIUM, DateFormat.SHORT).format(date) + " · device time"
        else shown(text) + " · server-reported time"
}
data class DetailField(val label: String, val value: String)
data class DetailCard(val title: String, val fields: List<DetailField>, val note: String? = null, val record: JsonObject? = null)
data class ArchiveDetail(val name: String, val size: String, val modified: String, val raw: JsonObject)
data class BackupDetails(val result: String, val resultNote: String, val files: String, val activity: String, val engine: String,
    val archives: List<ArchiveDetail>?, val schedule: String, val scheduleState: String, val scheduleNote: String,
    val retention: String, val sources: List<String>?, val remotes: List<String>?, val folder: String)

fun backupDetails(status: JsonElement?, setup: JsonElement?): BackupDetails {
    val root = status.obj(); val last = root?.get("last").obj(); val worker = root?.get("worker").obj()
    val settings = root?.get("settings").obj(); val backup = setup.obj()?.get("backup").obj()
    val cloud = setup.obj()?.get("cloud").obj(); val schedule = backup?.get("schedule").obj()
    val state = last.text("state") ?: last.text("status")
    val verified = last.flag("verified")
    val conflict = state == "verified" && verified == false
    val result = when {
        conflict -> "Conflicting verification status"
        verified == true || state == "verified" -> "Verified"
        verified == false -> "Not verified"
        state == "ok" -> "Completed · verification not reported"
        state != null -> words(state)
        last.text("last_success") != null -> "Latest result not reported"
        else -> "Unavailable"
    }
    val note = when {
        conflict -> "Latest-result fields disagree. Inspect additional server details."
        result == "Verified" -> "The latest run passed its verification check. This does not identify the contents of each stored archive."
        last.text("last_success") != null -> "Last successful run: ${last.text("last_success")} · server-reported time. Archive verification is not reported."
        else -> "Latest-run result is separate from the current worker activity and stored archives."
    }
    val activity = when (worker.text("state")) { "idle" -> "No job running"; "running", "busy" -> "Job running"; "stopped" -> "Worker stopped"; else -> words(worker.text("state") ?: worker.text("phase")) }
    val enabled = schedule.flag("enabled"); val summaryEnabled = settings.flag("schedule_enabled")
    val disagrees = enabled != null && summaryEnabled != null && enabled != summaryEnabled
    val scheduleState = if (disagrees) "Conflicting settings" else yesNo(enabled ?: summaryEnabled)
    val scheduleDescription = when (schedule.text("mode")) {
        "daily" -> schedule.text("time")?.takeIf { Regex("(?:[01]\\d|2[0-3]):[0-5]\\d").matches(it) }?.let { "Every day at $it" } ?: "Daily time unavailable"
        "interval" -> schedule.number("interval_hours")?.takeIf { it > 0 }?.let { "Every ${if (it % 1.0 == 0.0) it.toLong().toString() else it.toString()} hours" } ?: "Interval unavailable"
        "times" -> (schedule?.get("times") as? JsonArray)?.mapNotNull { (it as? JsonPrimitive)?.contentOrNull }?.joinToString(", ")?.ifBlank { "Configured times unavailable" } ?: "Configured times unavailable"
        else -> settings.text("schedule_time")?.takeIf { it.isNotBlank() }?.let { "Reported time $it · schedule mode unavailable" } ?: "Schedule unavailable"
    }
    fun strings(parent: JsonObject?, key: String) = (parent?.get(key) as? JsonArray)?.mapNotNull { (it as? JsonPrimitive)?.contentOrNull }
    val archives = root?.get("items").rows()?.map { row -> ArchiveDetail(shown(row.text("name")), detailBytes(row.count("size")), deviceTimestamp(row["modified"]), row) }
    return BackupDetails(result, note, last.count("files")?.toString() ?: "Unavailable", activity,
        when (root.flag("installed")) { true -> "Installed"; false -> "Not installed"; null -> "Unavailable" }, archives,
        scheduleDescription, scheduleState,
        if (disagrees) "Schedule responses disagree. Refresh to confirm the current setting." else "${backup.text("timezone") ?: "Server timezone not reported"}. Configured schedule only; an exact next run is not reported.",
        settings.count("keep_local_copies")?.takeIf { it > 0 }?.let { "Up to $it local copies" } ?: "Unavailable",
        strings(backup, "sources"), strings(cloud, "backup_targets"), shown(cloud.text("folder")))
}

/** Raw disclosures redact recursively and do not interpret unknown numeric values. */
fun redactedDetails(value: JsonElement): JsonElement = when (value) {
    is JsonObject -> JsonObject(value.filterKeys { key ->
        val name = key.lowercase()
        val sensitive = value.flag("secret") == true || value.text("type") == "secret" ||
            listOf("token", "password", "secret", "credential", "private_key", "passphrase").any { it in value.text("key").orEmpty().lowercase() }
        name != "png" && name !in setOf("key", "pass", "cookie", "csrf", "nonce", "authorization") &&
            !(sensitive && name in setOf("value", "default", "answer")) &&
            listOf("token", "password", "secret", "credential", "private_key", "passphrase").none { it in name }
    }.mapValues { redactedDetails(it.value) })
    is JsonArray -> JsonArray(value.map(::redactedDetails))
    else -> value
}
