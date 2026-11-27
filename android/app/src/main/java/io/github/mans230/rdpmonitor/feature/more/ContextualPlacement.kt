package io.github.mans230.rdpmonitor.feature.more

/** One owner for every native tool; the renderer uses this for section placement. */
internal fun toolSection(feature: Feature, tool: Tool): String = when (tool.action) {
    "block_ip", "unblock_ip", "block_subnet" -> "Addresses"
    "rdp" -> if (feature == Feature.Protection) "Access policy" else "Connection policy"
    "trap" -> "Account traps"
    "set_rdp_port" -> "Connection policy"
    "user" -> "Windows accounts"
    "logoff", "msg" -> "Remote sessions"
    "service" -> "Services"
    "start_program" -> "Programs"
    "run_command" -> "Command input"
    "kill" -> "Processes"
    "automation" -> "Recovery rules"
    "clean_temp" -> "Cleanup"
    "exportlogs", "send_file" -> "Logs & files"
    "reboot", "shutdown", "cancel_restart" -> "Power controls"
    "suite_update" -> if (tool.fixed["op"] == "configure") "Update policy" else "Suite updates"
    "mute", "test_alert" -> "Alert delivery"
    "settings_set" -> "Advanced settings"
    "drill" -> "Recovery checks"
    "restore" -> "Local archives"
    "backup_now" -> "Source folders"
    "setup" -> when {
        tool.fixed["op"].orEmpty().startsWith("image_") -> "System image"
        tool.fixed["op"] in setOf("test", "targets") -> "Cloud destinations"
        tool.fixed["op"] == "schedule" -> "Backup policy"
        tool.fixed["op"] == "sources" -> "Source folders"
        else -> "Cloud storage"
    }
    else -> error("No contextual owner for ${tool.action}")
}
internal fun documentSection(feature: Feature, path: String): String = when (path.substringBefore('?')) {
    "/api/security" -> "Addresses"
    "/api/rdp" -> if (feature == Feature.Protection) "Access policy" else "Connection policy"
    "/api/traps" -> "Account traps"
    "/api/users" -> "Windows accounts"
    "/api/stats" -> "Remote sessions"
    "/api/services" -> "Services"
    "/api/automation" -> "Recovery rules"
    "/api/suite-update" -> "Suite updates"
    "/api/setup" -> if (feature == Feature.Access) "Private access" else "Cloud storage"
    "/api/setup/jobs" -> "Cloud storage"
    "/api/mobile/v1/sessions" -> "App sessions"
    "/api/settings" -> "Monitoring policy"
    "/api/sysinfo" -> "System information"
    "/api/usage" -> "Recorded activity"
    "/api/docs" -> "Command reference"
    else -> "Report details"
}
internal val uncommonCloudOps = setOf("install", "create", "client", "delete")
