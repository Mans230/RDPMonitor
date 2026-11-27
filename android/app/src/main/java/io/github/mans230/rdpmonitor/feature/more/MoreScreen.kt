package io.github.mans230.rdpmonitor.feature.more

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowForward
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.unit.dp
import io.github.mans230.rdpmonitor.ui.components.*
import io.github.mans230.rdpmonitor.ui.theme.*

enum class Feature(val title: String, val summary: String, val capabilities: List<String>) {
    Protection("Protection", "RDP policy, firewall and account safety", listOf("RDP connectivity diagnostics", "Failed logins and grouped incidents", "Trusted IPs and blocked addresses", "Review before changing access")),
    Backups("Backups", "Archives, restore checks and schedules", listOf("Verified backup status", "Sources, retention and schedules", "Cloud destinations", "Restore and recovery review")),
    RdpAccess("RDP & users", "Sessions, access and local accounts", listOf("Active Windows sessions", "Local user inventory", "Session and account auditing", "Explicit confirmation for account changes")),
    Cloud("Cloud & images", "Guided cloud setup and system images", listOf("rclone account setup", "Backup and image upload destinations", "System image progress", "Archive and image verification")),
    Commands("Command center", "Commands grouped by their purpose", listOf("CPU & RAM", "Network & bandwidth", "Protection & accounts", "Programs & services", "Backups & recovery", "Settings & maintenance")),
    Updates("Updates", "Validated bot and panel releases", listOf("Current release and health", "Checksummed suite updates", "Installation status and rollback", "Preserve approved passkeys")),
    Access("Private access", "Tailscale, passkeys and owner approval", listOf("HTTPS over the private tailnet", "Passkey sign-in in the system browser", "Owner approval in Telegram", "No chat login tokens or public IP fallback")),
    Settings("Settings & alerts", "Monitoring thresholds, notifications and permissions", emptyList()),
    Processes("Processes", "Current CPU, memory and process controls", emptyList()),
    LocalUsers("Local users", "Local accounts and reviewed account changes", emptyList()),
    History("Resource history", "Recorded CPU, memory, network and storage", emptyList()),
    SystemTools("System tools", "Services and programs", emptyList()),
    Automation("Automation", "Watch, keep alive and process rules", emptyList()),
    Diagnostics("Diagnostics", "Read-only server reports", emptyList()),
    Reference("Command reference", "Server command documentation", emptyList()),
    Maintenance("Maintenance", "Cleanup, logs and power controls", emptyList())
}


@Composable fun MoreScreen(onFeature: (Feature) -> Unit, onConnections: () -> Unit,
    onBandwidth: () -> Unit = {}, onActivity: () -> Unit = {}) {
    var query by rememberSaveable { mutableStateOf("") }
    val account = LocalAppAccount.current
    val appearance = appearanceAction()
    val groups = listOf(
        "Monitor" to listOf(Feature.Processes, Feature.History, Feature.Diagnostics),
        "Protect" to listOf(Feature.Protection, Feature.RdpAccess, Feature.LocalUsers, Feature.Access),
        "Store & recover" to listOf(Feature.Backups, Feature.Cloud),
        "Manage" to listOf(Feature.Commands, Feature.SystemTools, Feature.Automation, Feature.Updates, Feature.Settings, Feature.Maintenance, Feature.Reference))
    PageTitle("All sections", "")
    CossField("Search functions", query, { query = it })
    groups.forEach { (title, features) ->
        val matches = features.filter { query.isBlank() || it.title.contains(query, true) || it.summary.contains(query, true) }
        val network = title == "Monitor" && (query.isBlank() || "Network bandwidth recorded usage".contains(query, true))
        val activity = title == "Monitor" && (query.isBlank() || "Activity events".contains(query, true))
        if (matches.isNotEmpty() || network || activity) Section(title) {
            matches.forEach { feature ->
                DirectoryRow(feature.title, Modifier.testTag("feature-${feature.name}")) { onFeature(feature) }
            }
            if (network) DirectoryRow("Network & bandwidth", onClick = onBandwidth)
            if (activity) DirectoryRow("Activity", onClick = onActivity)
        }
    }
    if (query.isBlank() || "Account appearance".contains(query, true)) Section("Account") {
        DirectoryRow("Account", onClick = account ?: onConnections)
        DirectoryRow("Appearance", onClick = appearance)
    }
}

@Composable internal fun DirectoryRow(title: String, modifier: Modifier = Modifier, onClick: () -> Unit) {
    Row(modifier.fillMaxWidth().clickable(onClick = onClick).heightIn(min = 48.dp), verticalAlignment = androidx.compose.ui.Alignment.CenterVertically) {
        Text(title, Modifier.weight(1f))
        Icon(Icons.AutoMirrored.Outlined.ArrowForward, "Open $title", Modifier.size(18.dp), tint = Muted)
    }
}
