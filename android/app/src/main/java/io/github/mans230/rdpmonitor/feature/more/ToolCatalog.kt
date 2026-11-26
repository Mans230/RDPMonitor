package io.github.mans230.rdpmonitor.feature.more

import kotlinx.serialization.json.*

data class ToolField(val key: String, val label: String, val kind: String = "text", val options: List<String> = emptyList(), val optional: Boolean = false)
data class Tool(val title: String, val effect: String, val action: String, val fixed: Map<String, String> = emptyMap(), val fields: List<ToolField> = emptyList()) {
    fun visibleFields(values: Map<String, String>) = fields.filter { !it.key.startsWith("options.") || it.key.removePrefix("options.") in providerOptions(values["provider"].orEmpty()) }
    fun safeArguments(body: JsonObject): JsonObject {
        fun redact(value: JsonElement, path: String = ""): JsonElement = when (value) {
            is JsonObject -> JsonObject(value.mapValues { (key, item) ->
                val full = if (path.isEmpty()) key else "$path.$key"
                if (key.lowercase() in setOf("password", "pass", "secret", "token", "client_secret", "secret_access_key", "access_token", "refresh_token") || full == "options.key" || fields.any { it.key == full && it.kind == "secret" }) JsonPrimitive("Hidden") else redact(item, full)
            })
            is JsonArray -> JsonArray(value.map { redact(it, path) })
            else -> value
        }
        return redact(JsonObject(body.filterKeys { it !in setOf("action", "confirm", "nonce") })).jsonObject
    }
    fun payload(values: Map<String, String>): JsonObject = buildJsonObject {
        put("action", action); put("confirm", true)
        fixed.forEach { (key, value) -> put(key, value) }
        val options = mutableMapOf<String, JsonElement>()
        visibleFields(values).forEach { field ->
            val value = values[field.key].orEmpty().trim()
            require(field.optional || value.isNotEmpty()) { "${field.label} is required." }
            require(value.length <= 16000) { "${field.label} is too long." }
            if (field.options.isNotEmpty()) require(value in field.options) { "Choose ${field.label}." }
            if (field.key.startsWith("options.")) {
                if (value.isNotEmpty()) options[field.key.removePrefix("options.")] = JsonPrimitive(value)
                return@forEach
            }
            when (field.kind) {
                "int" -> { if (value.isNotEmpty()) put(field.key, value.toIntOrNull() ?: error("${field.label} must be a whole number.")) }
                "bool" -> { require(value in listOf("true", "false")); put(field.key, value == "true") }
                "lines", "paths" -> put(field.key, JsonArray(value.lines().filter { it.isNotBlank() }.map { JsonPrimitive(it.trim()) }))
                "pids" -> { val ids = value.split(',', ' ', '\n').filter { it.isNotBlank() }.map { it.toIntOrNull()?.takeIf { n -> n > 0 } ?: error("Enter valid process IDs.") }; require(ids.isNotEmpty()); put(field.key, JsonArray(ids.map(::JsonPrimitive))) }
                "options" -> { val obj = if (value.isEmpty()) JsonObject(emptyMap()) else Json.parseToJsonElement(value).jsonObject; put(field.key, obj) }
                else -> if (value.isNotEmpty() || !field.optional) put(field.key, value)
            }
        }
        if (fields.any { it.key.startsWith("options.") }) put("options", JsonObject(options))
    }
}
fun providerOptions(provider: String): Set<String> = when (provider) {
    "s3" -> setOf("provider", "access_key_id", "secret_access_key", "endpoint", "region")
    "b2" -> setOf("account", "key", "endpoint")
    "sftp" -> setOf("host", "user", "pass", "port", "key_file")
    "ftp" -> setOf("host", "user", "pass", "port")
    "webdav" -> setOf("url", "vendor", "user", "pass")
    else -> emptySet()
}
private fun f(key: String, label: String, kind: String = "text", options: List<String> = emptyList(), optional: Boolean = false) = ToolField(key, label, kind, options, optional)
private fun choice(key: String, label: String, vararg options: String) = f(key, label, options = options.toList())
private fun setup(title: String, op: String, vararg fields: ToolField) = Tool(title, "Change server setup: $title. Existing server checks and job status apply.", "setup", mapOf("op" to op), fields.toList())

object ToolCatalog {
    fun documents(feature: Feature): List<Pair<String, String>> = when (feature) {
        Feature.Protection -> listOf("Protection" to "/api/security", "RDP policy" to "/api/rdp", "Account traps" to "/api/traps")
        Feature.Backups -> listOf("Backup status" to "/api/backup", "Sources and schedule" to "/api/setup", "Operations" to "/api/setup/jobs")
        Feature.RdpAccess -> listOf("RDP policy" to "/api/rdp", "Local users" to "/api/users", "Active sessions" to "/api/stats")
        Feature.Cloud -> listOf("Cloud and images" to "/api/setup", "Operations" to "/api/setup/jobs")
        Feature.Commands -> listOf("Services" to "/api/services", "Automation" to "/api/automation?list=watch", "Keep alive" to "/api/automation?list=keepalive")
        Feature.Updates -> listOf("Suite updater" to "/api/suite-update")
        Feature.Access -> listOf("Private access" to "/api/setup", "App sessions" to "/api/mobile/v1/sessions")
        Feature.Settings -> listOf("Settings" to "/api/settings", "Usage" to "/api/usage")
    }
    fun tools(feature: Feature): List<Tool> = when (feature) {
        Feature.Protection -> listOf(
            Tool("Block address", "Block this address in Windows Firewall.", "block_ip", fields=listOf(f("ip", "IP address"))),
            Tool("Unblock address", "Remove the managed block for this address.", "unblock_ip", fields=listOf(f("ip", "IP address"))),
            Tool("Block subnet", "Block this subnet. It may affect other users.", "block_subnet", fields=listOf(f("ip", "Subnet"))),
            Tool("Lockdown", "Change the RDP lockdown state. This can interrupt access.", "rdp", mapOf("op" to "lockdown"), listOf(choice("mode", "State", "on", "off"))),
            Tool("Panic protection", "Panic ON closes RDP access until released.", "rdp", mapOf("op" to "panic"), listOf(choice("mode", "State", "on", "off"))),
            Tool("Account trap", "Add or remove a monitored trap account.", "trap", fields=listOf(choice("op", "Operation", "add", "del"), f("name", "Account name"))))
        Feature.Backups -> listOf(
            Tool("Back up now", "Start a backup job using the configured sources and destinations.", "backup_now"),
            Tool("Restore verification drill", "Run the configured restore verification drill.", "drill"),
            Tool("Restore archive", "Restore the selected archive on the server. Review the archive name carefully.", "restore", fields=listOf(f("name", "Archive name"))),
            setup("Save backup sources", "sources", f("paths", "Server folders · one per line", "paths")),
            setup("Save backup schedule", "schedule", choice("mode", "Mode", "daily", "interval", "times"), f("value", "HH:MM, hours, or comma-separated times"), f("enabled", "Enabled", "bool", listOf("true", "false"))),
            setup("Save cloud destinations", "targets", f("image", "Image destination · remote:folder", optional=true), f("backups", "Backup remotes · one remote: per line", "lines"), f("folder", "Backup cloud folder")))
        Feature.Cloud -> listOf(
            setup("Install verified rclone", "install"),
            setup("Connect cloud account", "authorize", f("name", "New remote name"), choice("provider", "Provider", "drive", "onedrive", "dropbox")),
            setup("Create storage remote", "create", f("name", "New remote name"), choice("provider", "Provider", "s3", "b2", "sftp", "ftp", "webdav"),
                f("options.provider", "S3 provider", options=listOf("AWS", "Cloudflare", "Minio", "Other"), optional=true),
                f("options.access_key_id", "Access key ID", optional=true), f("options.secret_access_key", "Secret access key", "secret", optional=true),
                f("options.endpoint", "Endpoint", optional=true), f("options.region", "Region", optional=true),
                f("options.account", "Account ID", optional=true), f("options.key", "Application key", "secret", optional=true),
                f("options.host", "Host", optional=true), f("options.user", "User", optional=true), f("options.pass", "Password", "secret", optional=true),
                f("options.port", "Port", optional=true), f("options.key_file", "Server SSH key file", "path", optional=true),
                f("options.url", "WebDAV URL", optional=true), f("options.vendor", "WebDAV vendor", optional=true)),
            setup("Import OAuth token", "create", f("name", "New remote name"), choice("provider", "Provider", "drive", "onedrive", "dropbox"), f("token", "OAuth JSON", "secret")),
            setup("Set OAuth client", "client", f("name", "Existing remote"), f("client_id", "Client ID"), f("client_secret", "Client secret", "secret")),
            setup("Test cloud destination", "test", f("target", "Remote destination")),
            setup("Remove cloud remote", "delete", f("name", "Remote name")),
            setup("Save cloud destinations", "targets", f("image", "Image target · remote:folder", optional=true), f("backups", "Backup remotes · one per line", "lines"), f("folder", "Backup folder")),
            setup("Create system image", "image_start"), setup("Upload system image", "image_upload", f("path", "Existing image path", "file")),
            setup("Stop image operation", "image_stop"), setup("Send image link to Telegram", "image_link", f("path", "Existing image path", "file")))
        Feature.RdpAccess -> listOf(
            Tool("Manage local user", "Change a Windows account. Passwords are not shown in the review.", "user", fields=listOf(choice("op", "Operation", "add", "enable", "disable", "delete", "password", "rename"), f("name", "User name"), f("value", "Password or new name when required", "secret", optional=true))),
            Tool("Add trusted address", "Add an address to the RDP allow-list.", "rdp", mapOf("op" to "rdp_allow_add"), listOf(f("ip", "Address or CIDR"))),
            Tool("Remove trusted address", "Remove an address from the RDP allow-list.", "rdp", mapOf("op" to "rdp_allow_remove"), listOf(f("ip", "Address or CIDR"))),
            Tool("Apply RDP allow-list", "Restrict RDP to the configured allow-list. This may disconnect clients.", "rdp", mapOf("op" to "rdp_allow_apply")),
            Tool("Clear RDP allow-list", "Remove allow-list restrictions. RDP may become accessible more broadly.", "rdp", mapOf("op" to "rdp_allow_clear")),
            Tool("Change RDP port", "Change the server's RDP port; clients must reconnect on the new port.", "set_rdp_port", fields=listOf(f("port", "Port", "int"))),
            Tool("Log off session", "End this Windows session. Unsaved work may be lost.", "logoff", fields=listOf(f("sid", "Session ID"))),
            Tool("Message sessions", "Display a message to logged-in Windows users.", "msg", fields=listOf(f("text", "Message"))))
        Feature.Commands -> listOf(
            Tool("Run command", "Execute a command on the server if both execution permissions are enabled.", "run_command", fields=listOf(f("cmd", "Command"))),
            Tool("Manage service", "Start, stop or restart a Windows service.", "service", fields=listOf(f("name", "Service name"), choice("mode", "Operation", "start", "stop", "restart"))),
            Tool("Start program", "Start this program on the server.", "start_program", fields=listOf(f("path", "Program path", "file"), f("args", "Arguments", optional=true))),
            Tool("Stop processes", "Terminate these processes. Unsaved data may be lost.", "kill", fields=listOf(f("pids", "Process IDs · comma-separated", "pids"))),
            Tool("Clean temporary files", "Delete eligible server temporary files.", "clean_temp"),
            Tool("Export logs to Telegram", "Prepare server logs and send the archive to the configured chat.", "exportlogs", fields=listOf(choice("scope", "Logs", "all", "system", "application"))),
            Tool("Send file to Telegram", "Send this server file to the configured Telegram chat.", "send_file", fields=listOf(f("path", "Server file", "file"))),
            Tool("Automation rule", "Add or remove a process automation rule.", "automation", fields=listOf(choice("list", "List", "watch", "keepalive", "autokill"), choice("op", "Operation", "add", "del"), f("name", "Process name"), f("ram_mb", "Memory threshold MiB", "int", optional=true), f("run", "Restart command", optional=true))),
            Tool("Reboot server", "Restart Windows. All active users may be disconnected.", "reboot"),
            Tool("Shut down server", "Power off Windows. Remote access will stop.", "shutdown"),
            Tool("Cancel scheduled restart", "Cancel the server's pending restart if supported.", "cancel_restart"))
        Feature.Updates -> listOf(
            Tool("Check for suite updates", "Check the validated release channel.", "suite_update", mapOf("op" to "check")),
            Tool("Install suite update", "Install the validated bot/panel release. Services restart during installation.", "suite_update", mapOf("op" to "apply")),
            Tool("Configure automatic updates", "Save the automatic update policy.", "suite_update", mapOf("op" to "configure"), listOf(f("enabled", "Enabled", "bool", listOf("true", "false")), f("hours", "Check interval hours", "int"))))
        Feature.Access -> emptyList()
        Feature.Settings -> listOf(
            Tool("Change setting", "Save this server setting using its documented key and value.", "settings_set", fields=listOf(f("key", "Setting key"), f("value", "Value"))),
            Tool("Mute alerts", "Mute Telegram alerts for this many minutes.", "mute", fields=listOf(f("minutes", "Minutes", "int"))),
            Tool("Resume alerts", "Stop the alert mute.", "mute", fields=listOf(f("off", "Resume", "bool", listOf("true")))),
            Tool("Send test alert", "Send a test notification to the configured Telegram chat.", "test_alert"))
    }
}
