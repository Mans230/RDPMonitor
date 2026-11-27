package io.github.mans230.rdpmonitor.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.unit.dp
import io.github.mans230.rdpmonitor.AppState
import io.github.mans230.rdpmonitor.RdpViewModel
import io.github.mans230.rdpmonitor.core.model.ServerProfile
import io.github.mans230.rdpmonitor.ui.components.*
import io.github.mans230.rdpmonitor.ui.theme.*

@Composable fun WorkspaceLink(title: String, onClick: () -> Unit, enabled: Boolean = true) {
    Row(Modifier.fillMaxWidth().heightIn(min = 48.dp).motionClickable(enabled = enabled, onClick = onClick),
        verticalAlignment = androidx.compose.ui.Alignment.CenterVertically) {
        Text(title, Modifier.weight(1f))
        Icon(CossIcons.ArrowRight, null, Modifier.size(18.dp), tint = Muted)
    }
}

@Composable fun AccountContent(name: String, email: String, onServers: () -> Unit, onSignOut: () -> Unit) {
    PageTitle("Account", "")
    CossFrame("Your account") { CossPanel {
        Text(name.ifBlank { "Google account" }, style = MaterialTheme.typography.titleMedium)
        if (email.isNotBlank()) Text(email, color = Muted)
        WorkspaceLink("Server connections", onServers)
        val appearance = appearanceAction()
        WorkspaceLink("Appearance", appearance)
    } }
    Spacer(Modifier.height(18.dp))
    CossFrame("App access") { CossPanel {
        CossOutlinedButton(onClick = onSignOut, modifier = Modifier.fillMaxWidth()) { Text("Sign out") }
    } }
}

@Composable fun ServerWorkspaceContent(state: AppState, model: RdpViewModel,
    onAdd: () -> Unit, onReconnect: (ServerProfile) -> Unit) {
    val available = !state.busy && !state.actionBusy
    var inspected by remember { mutableStateOf<ServerProfile?>(null) }
    var removing by remember { mutableStateOf<ServerProfile?>(null) }
    var disconnecting by remember { mutableStateOf(false) }
    PageTitle("Server connections", "")
    Spacer(Modifier.height(18.dp))
    CossFrame("Your servers", headerActions = { CossOutlinedButton(onClick = onAdd, enabled = available) { Text("Add server") } }) { CossPanel {
        if (state.profiles.isEmpty()) Text("No servers added yet.", color = Muted)
        LazyColumn(Modifier.fillMaxWidth().heightIn(max = 320.dp).testTag("saved-servers-list")) { items(state.profiles, key = { it.id }) { server ->
            Row(Modifier.fillMaxWidth().testTag("server-${server.id}").heightIn(min = 56.dp).motionClickable(enabled = available) { inspected = server },
                verticalAlignment = androidx.compose.ui.Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text(server.name)
                    Text(server.origin.removePrefix("https://"), color = Muted, style = MaterialTheme.typography.bodySmall)
                }
                Icon(CossIcons.ArrowRight, "Server settings for ${server.name}", Modifier.size(18.dp))
            }
        } }
    } }
    state.selected?.takeIf { current -> state.profiles.any { it.id == current.id } }?.let { server ->
        Spacer(Modifier.height(18.dp))
        CossFrame("Selected connection") { CossPanel {
            MetricRow("Server", server.name)
            MetricRow("State", if (state.connected) "Connected" else if (state.busy) "Connecting" else "Disconnected")
            CossOutlinedButton(onClick = { onReconnect(server) }, enabled = available) { Text("Reconnect") }
            CossOutlinedButton(onClick = { disconnecting = true }, enabled = available && state.connected) { Text("Disconnect") }
        } }
    }
    inspected?.let { server ->
        CossDialog(onDismissRequest = { inspected = null }, title = { Text(server.name) }, text = {
            Text(server.origin, color = Muted)
            WorkspaceLink("Reconnect", { inspected = null; onReconnect(server) }, available)
            if (state.connected && state.selected?.id == server.id) WorkspaceLink("Disconnect", { inspected = null; disconnecting = true }, available)
            WorkspaceLink("Remove saved server", { inspected = null; removing = server }, available)
        }, confirmButton = { CossOutlinedButton(onClick = { inspected = null }, modifier = Modifier.fillMaxWidth()) { Text("Done") } })
    }
    removing?.let { server -> CossDialog(onDismissRequest = { removing = null }, title = { Text("Remove ${server.name}?") },
        text = { Text("Remove this saved connection from this account on this device. The Windows server is unchanged.") },
        confirmButton = { CossButton(onClick = { model.remove(server); removing = null }, enabled = available, modifier = Modifier.fillMaxWidth()) { Text("Remove server") } },
        dismissButton = { CossOutlinedButton(onClick = { removing = null }, modifier = Modifier.fillMaxWidth()) { Text("Cancel") } }) }
    if (disconnecting) CossDialog(onDismissRequest = { disconnecting = false }, title = { Text("Disconnect ${state.selected?.name}?") },
        text = { Text("End this server session. Your Google sign-in and saved servers are kept.") },
        confirmButton = { CossButton(onClick = { model.disconnect(); disconnecting = false }, enabled = available, modifier = Modifier.fillMaxWidth()) { Text("Disconnect") } },
        dismissButton = { CossOutlinedButton(onClick = { disconnecting = false }, modifier = Modifier.fillMaxWidth()) { Text("Cancel") } })
}
