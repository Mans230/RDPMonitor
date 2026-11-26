package io.github.mans230.rdpmonitor.ui.components

import kotlinx.serialization.json.*
import java.text.DateFormat
import java.util.Date

fun scopeTitle(scope: String) = if (scope == "administration") "Administration" else "Monitoring only"
fun diagnosticTitle(op: String) = mapOf("diagnose" to "Server health report", "logstats" to "Event log summary", "logs" to "Windows event logs",
    "firewall" to "Firewall status", "netstat" to "Network connections", "when" to "Session timeline", "ps" to "Process report", "bigfiles" to "Find large files",
    "temp" to "Temporary file usage", "startup" to "Startup programs", "updates" to "Windows updates", "sysinfo" to "System information", "harden" to "Security posture",
    "report" to "Monitoring report", "logins" to "Login history", "botlog" to "Bot log", "dumps" to "Recent crash reports", "speedtest" to "Network speed test", "nettest" to "Test a network host")[op] ?: op
fun diagnosticHint(op: String) = when (op) {
    "nettest" -> "Enter a host name or IP address, for example 1.1.1.1."
    "logs" -> "Optional: days and severity, for example 7 error."
    "diagnose", "logstats", "logins" -> "Optional: number of days (1–30). Leave empty for the server default."
    "bigfiles" -> "Optional: server folder to inspect. Results can take time on large disks."
    "speedtest" -> "Measures server network speed. It can take a few minutes and uses network traffic. No parameters are needed."
    else -> "Leave parameters empty to use the server's default report."
}
fun readableValue(key: String, value: JsonPrimitive): String {
    if (value is JsonNull) return "Unavailable"
    val name = key.lowercase()
    value.booleanOrNull?.let { yes -> return when {
        name == "healthy" -> if (yes) "Healthy" else "Needs attention"
        name == "installed" -> if (yes) "Installed" else "Not installed"
        name.endsWith("enabled") -> if (yes) "Enabled" else "Disabled"
        else -> if (yes) "Yes" else "No"
    } }
    value.doubleOrNull?.let { number ->
        if (number.isFinite() && name in setOf("size", "rss", "free", "used", "avail", "quota_bytes", "quota_remaining") || number.isFinite() && name.endsWith("_bytes"))
            return bytes(number.toLong())
        if (number in 100_000_000.0..10_000_000_000.0 && name in setOf("t", "ts", "modified", "created", "started", "finished", "expires", "collected_at"))
            return DateFormat.getDateTimeInstance(DateFormat.MEDIUM, DateFormat.SHORT).format(Date((number * 1000).toLong()))
    }
    return value.content.ifBlank { "Not configured" }
}
