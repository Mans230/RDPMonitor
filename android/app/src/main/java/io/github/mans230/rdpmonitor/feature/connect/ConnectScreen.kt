package io.github.mans230.rdpmonitor.feature.connect

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Close
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import io.github.mans230.rdpmonitor.*
import io.github.mans230.rdpmonitor.ui.components.*
import io.github.mans230.rdpmonitor.ui.theme.*

@Composable fun ConnectScreen(state: AppState, model: RdpViewModel, openBrowser: (String) -> Unit, modifier: Modifier = Modifier) {
    var name by rememberSaveable { mutableStateOf("") }
    var address by rememberSaveable { mutableStateOf("") }
    Column(modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(20.dp), verticalArrangement = Arrangement.spacedBy(24.dp)) {
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) { PulseMark(); Text("RDPMonitor", style = MaterialTheme.typography.titleLarge) }
        if (state.snapshot != null && state.connectionScreen) {
            TextButton(onClick = model::closeConnections) { Text("Back to ${if (state.demo) "demo" else state.selected?.name ?: "monitor"}") }
            Notice(if (state.demo) "Choose a server below, or return to the demo." else "Your current server session is kept. Opening this screen does not sign you out.")
        }
        PageTitle("Connect your server", "Windows monitoring and control, through your private network.")
        Notice("Connect Tailscale on this device. Sign-in uses your saved passkey; new keys require your approval in Telegram.")
        Section("Private connection") {
            OutlinedTextField(value = name, onValueChange = { name = it }, label = { Text("Server name") }, singleLine = true,
                modifier = Modifier.fillMaxWidth(), enabled = !state.busy)
            OutlinedTextField(value = address, onValueChange = { address = it }, label = { Text("Private HTTPS address") },
                placeholder = { Text("https://server.tailnet.ts.net") }, singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri), modifier = Modifier.fillMaxWidth(), enabled = !state.busy)
            state.message?.let { Notice(it) }
            Button(onClick = { model.connect(name, address, openBrowser) }, modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp),
                enabled = !state.busy, colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.onSurface, contentColor = Ground)) {
                if (state.busy) CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp, color = Ground)
                else Text("Check private connection")
            }
            state.selected?.let { profile ->
                TextButton(onClick = { openBrowser(profile.origin + "/") }, modifier = Modifier.fillMaxWidth()) { Text("Open secure web panel") }
            }
        }
        if (state.profiles.isNotEmpty()) {
            Section("Saved servers", "Addresses are stored on this device. No bot token is needed.") {
                state.profiles.forEach { profile ->
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Column(Modifier.weight(1f).clickable(enabled = !state.busy) { name = profile.name; address = profile.origin }.padding(vertical = 8.dp)) {
                            Text(profile.name, style = MaterialTheme.typography.bodyLarge)
                            Text(profile.origin.removePrefix("https://"), color = Muted, style = MaterialTheme.typography.bodyMedium)
                        }
                        IconButton(onClick = { model.remove(profile) }, enabled = !state.busy) { Icon(Icons.Outlined.Close, "Remove saved server ${profile.name}") }
                    }
                }
            }
        }
        OutlinedButton(onClick = model::preview, enabled = !state.busy, modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp)) { Text("Explore offline demo") }
        Text("The demo uses labelled sample data and cannot change a server.", color = Muted, style = MaterialTheme.typography.bodyMedium)
    }
}
