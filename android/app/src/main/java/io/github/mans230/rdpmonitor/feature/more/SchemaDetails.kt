package io.github.mans230.rdpmonitor.feature.more

import kotlinx.serialization.json.*

/** API-specific labels and units. Unknown fields stay in the raw disclosure, not guessed metrics. */
fun schemaCards(feature: Feature, path: String, data: JsonElement): List<DetailCard>? {
    val root = data.obj() ?: return null
    fun field(label: String, value: String?) = DetailField(label, shown(value))
    fun rows(key: String = "items") = root[key].rows()
    fun strings(parent: JsonObject?, key: String) = (parent?.get(key) as? JsonArray)?.mapNotNull { (it as? JsonPrimitive)?.contentOrNull }
    fun collection(title: String, noun: String, values: List<JsonObject>?, render: (JsonObject) -> DetailCard): List<DetailCard> =
        listOf(DetailCard(title, listOf(field("$noun reported", values?.size?.toString())), if (values == null) "No structured list was received." else if (values.isEmpty()) "No entries were reported." else null)) + values.orEmpty().map(render)
    fun sessions(values: List<JsonObject>?) = collection("Windows sessions", "Sessions", values) { row -> DetailCard(shown(row.text("user")), listOf(
        field("Windows session name", row.text("session")), field("Windows session ID", row.text("id")), field("Connection state", words(row.text("state"))))) }
    return when (path.substringBefore('?')) {
        "/api/rdp" -> listOf(DetailCard("RDP policy", listOf(
            field("Configured TCP port", root.count("port")?.toString()), field("RDP allowlist", yesNo(root.flag("allow_active"))),
            field("Blocked addresses", root.count("blocked_count")?.toString()), field("Lockdown mode", yesNo(root.flag("lockdown"))),
            field("Panic protection", yesNo(root.flag("panic"))), field("Configured allowed addresses", strings(root, "allowed_ips")?.let { if (it.isEmpty()) "None configured" else it.joinToString("\n") })),
            "These are reported policy settings, not proof that RDP is reachable externally."))
        "/api/users" -> collection("Local accounts", "Accounts", rows()) { row -> DetailCard(shown(row.text("name")), listOf(
            field("Account sign-in", yesNo(row.flag("enabled"))), field("Last sign-in reported by Windows", windowsLogon(row["last"]))), "Windows account sign-in, separate from the current app session.") }
        "/api/stats" -> sessions(root["sessions"].rows())
        "/api/security" -> {
            val blocked = root["blocked"].obj()
            listOf(DetailCard("Blocked addresses", listOf(field("Addresses in the reported block list", blocked?.size?.toString())))) +
                blocked?.entries.orEmpty().map { (address, record) -> DetailCard(address, listOf(field("Block reason", record.obj().text("reason")))) } + sessions(root["sessions"].rows())
        }
        "/api/services" -> collection("Windows service inventory", "Services", rows()) { row -> DetailCard(shown(row.text("display") ?: row.text("display_name") ?: row.text("name")), listOf(
            field("Windows service name", row.text("name")), field("Service status", row.text("status")))) }
        "/api/automation" -> {
            val list = path.substringAfter("list=", "")
            val title = when (list) { "watch" -> "Memory watch rules"; "keepalive" -> "Keep-alive rules"; "svcwatch" -> "Service watch rules"; else -> "Automation rules" }
            collection(title, "Rules", rows()) { row -> DetailCard(shown(row.text("name")), buildList {
                if (list == "watch") add(field("Memory threshold (MiB)", row.number("ram_mb")?.toString()?.removeSuffix(".0")))
                if (list == "keepalive") add(field("Custom restart command", row.text("run") ?: "No custom command reported"))
            }, note = if (list == "svcwatch") "Configured service-watch rule; this does not report the service's current running state." else null) }
        }
        "/api/traps" -> {
            val names = (root["items"] as? JsonArray)?.mapNotNull { (it as? JsonPrimitive)?.contentOrNull ?: it.obj().text("name") }
            listOf(DetailCard("Configured trap names", listOf(field("Trap names configured", names?.size?.toString())) + names.orEmpty().map { field("Monitored sign-in name", it) },
                "This is a configured trap-name list, not an inventory of enabled Windows accounts."))
        }
        "/api/mobile/v1/sessions" -> collection("Authorized native app sessions", "App sessions", rows()) { row -> DetailCard("App session", listOf(
            field("Session reference", row.text("id")), field("Authorized app access", when (row.text("scope")) { "administration" -> "Administration"; "monitoring:read" -> "Monitoring only"; else -> row.text("scope") }),
            field("App session created", deviceTimestamp(row["created"])), field("Reported app session expiry", deviceTimestamp(row["expires"]))), record = row) }
        "/api/setup/jobs" -> collection("Server setup operations", "Operations", root["jobs"].rows()) { row -> DetailCard(words(row.text("op")), listOf(
            field("Operation status", words(row.text("state"))), field("Server message", row.text("message")), field("Operation started", deviceTimestamp(row["started"])),
            field("Operation finished", deviceTimestamp(row["finished"]))), record = row) }
        "/api/sysinfo" -> listOf(DetailCard("Windows host", listOf(field("Host name", root.text("hostname")), field("Operating system", root.text("os")),
            field("OS build", root.text("version")), field("CPU architecture", root.text("arch")), field("Processor model", root.text("cpu_model")),
            field("Logical CPU cores", root.count("cores")?.toString()), field("Installed memory", detailBytes(root.count("ram_total"))),
            field("Host uptime", root.count("uptime_s")?.let { "${it / 86400}d ${(it % 86400) / 3600}h ${(it % 3600) / 60}m" } ?: root.number("uptime_s")?.let { "${it.toLong() / 3600}h ${(it.toLong() % 3600) / 60}m" }),
            field("Windows boot time", deviceTimestamp(root["boot"]))))) + root["disks"].rows().orEmpty().map { disk -> DetailCard(shown(disk.text("dev")), listOf(
                field("Volume capacity", detailBytes(disk.count("total"))), field("Available disk space", detailBytes(disk.count("free"))))) }
        "/api/suite-update" -> {
            val settings = root["settings"].obj(); val state = root["state"].obj()
            listOf(DetailCard("Suite updater", listOf(field("Updater task installed", when (root.flag("installed")) { true -> "Installed"; false -> "Not installed"; null -> "Unavailable" }),
                field("Installed commit", root.text("current")), field("Update phase", words(state.text("phase"))), field("Update message", state.text("message")),
                field("Automatic update checks", yesNo(settings.flag("enabled"))), field("Check interval (hours)", settings.count("interval_hours")?.toString()),
                field("Reported next update check", deviceTimestamp(root["next_check"]))), "Update checks are separate from installing a release."))
        }
        "/api/usage" -> listOf(DetailCard("Recorded operation usage", listOf(field("Events in the returned audit history", root.count("events")?.toString())), "Counts cover the server's returned history; no calendar period is inferred.")) +
            listOf("by_actor" to "Events by actor", "by_action" to "Events by operation", "by_status" to "Events by result").map { (key, title) ->
                DetailCard(title, root[key].obj()?.entries.orEmpty().map { (name, count) -> field(name, (count as? JsonPrimitive)?.longOrNull?.takeIf { it >= 0 }?.let { "$it events" }) })
            }
        "/api/setup" -> if (feature == Feature.Access) listOf(DetailCard("Private panel access", listOf(field("Access method", root.text("mode")),
            field("Authentication", root.text("auth") ?: root.text("authentication")), field("Private panel configured", yesNo(root.flag("configured"))), field("Private HTTPS address", root.text("url")))))
            else if (feature == Feature.Cloud) {
                val cloud = root["cloud"].obj(); val images = root["images"].obj(); val remotes = strings(cloud, "remotes")
                listOf(DetailCard("Cloud configuration", listOf(field("rclone health check", when (cloud.flag("healthy")) { true -> "Passed"; false -> "Failed or unavailable"; null -> "Unavailable" }),
                    field("rclone version", cloud.text("version")), field("Configured storage remotes", remotes?.let { if (it.isEmpty()) "None configured" else it.joinToString("\n") }),
                    field("System image upload destination", cloud.text("image_target"))), "Configured destinations do not prove an upload succeeded."),
                    DetailCard("System image operation", listOf(field("System imaging enabled", yesNo(images.flag("enabled"))), field("Reported operation phase", words(images.text("phase"))),
                        field("Current operation image file", images.text("file")), field("Current operation remote", images.text("remote")), field("Server operation detail", images.text("detail")),
                        field("Reported upload progress (%)", images.number("percent")?.takeIf { it <= 100 }?.toString()?.removeSuffix(".0"))))) + images?.get("files").rows().orEmpty().map { row -> DetailCard("Stored system image", listOf(
                            field("Image path on server", row.text("path")), field("Image size", detailBytes(row.count("size"))), field("Image last modified", deviceTimestamp(row["modified"])))) }
            } else null
        else -> null
    }
}
