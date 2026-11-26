package io.github.mans230.rdpmonitor.feature.overview

import kotlinx.serialization.json.*

data class BackupLead(val value: String, val schedule: String, val lastRun: String)

/** Describe the server's schedule; never infer a next run using the phone's timezone. */
fun backupLead(setup: JsonElement?, status: JsonElement?): BackupLead {
    val backup = (setup as? JsonObject)?.get("backup") as? JsonObject
    val schedule = backup?.get("schedule") as? JsonObject
    fun JsonObject?.text(key: String) = (this?.get(key) as? JsonPrimitive)?.contentOrNull
    val enabled = (schedule?.get("enabled") as? JsonPrimitive)?.booleanOrNull
    val timezone = backup.text("timezone") ?: "Server local time"
    val value = when {
        enabled == false -> "Not scheduled"
        enabled != true -> "Unavailable"
        schedule.text("mode") == "daily" -> schedule.text("time") ?: "Time unavailable"
        schedule.text("mode") == "interval" -> schedule.text("interval_hours")?.let { "Every $it hours" } ?: "Interval unavailable"
        schedule.text("mode") == "times" -> (schedule.get("times") as? JsonArray)?.mapNotNull { (it as? JsonPrimitive)?.contentOrNull }?.joinToString(", ")?.ifBlank { "Times unavailable" } ?: "Times unavailable"
        else -> "Schedule unavailable"
    }
    val description = when (enabled) {
        false -> "Automatic backups are disabled"
        null -> "Open Backups to load the server schedule"
        true -> "${if (schedule.text("mode") == "daily") "Daily · " else ""}$timezone · next run time not reported"
    }
    val last = (status as? JsonObject)?.get("last") as? JsonObject
    // A successful run is not evidence of verified archive integrity.
    val verified = (last?.get("verified") as? JsonPrimitive)?.booleanOrNull
    val lastText = when {
        verified == true -> "Last archive verified${last.text("archive")?.let { " · $it" } ?: ""}"
        verified == false -> "Last archive not verified"
        last.text("last_success") != null -> "Last successful run · ${last.text("last_success")?.replace('T', ' ')} (server time)"
        else -> (last.text("state") ?: last.text("status"))?.let { "Last run · ${it.replace('_', ' ')}" } ?: "Last run status unavailable"
    }
    return BackupLead(value, description, lastText)
}
