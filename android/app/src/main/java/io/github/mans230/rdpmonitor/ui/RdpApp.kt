package io.github.mans230.rdpmonitor.ui

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.foundation.selection.selectable
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ShowChart
import androidx.compose.material.icons.automirrored.outlined.ArrowBack
import androidx.compose.material.icons.automirrored.outlined.List
import androidx.compose.material.icons.outlined.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import io.github.mans230.rdpmonitor.*
import io.github.mans230.rdpmonitor.data.DemoData
import io.github.mans230.rdpmonitor.feature.activity.ActivityScreen
import io.github.mans230.rdpmonitor.feature.bandwidth.BandwidthScreen
import io.github.mans230.rdpmonitor.feature.connect.ConnectScreen
import io.github.mans230.rdpmonitor.feature.more.*
import io.github.mans230.rdpmonitor.feature.overview.OverviewScreen
import io.github.mans230.rdpmonitor.ui.components.*
import io.github.mans230.rdpmonitor.ui.theme.*

@Composable fun RdpApp(model: RdpViewModel, openBrowser: (String) -> Unit) {
    val state by model.state.collectAsStateWithLifecycle()
    var detail by rememberSaveable { mutableStateOf<String?>(null) }
    var signOut by rememberSaveable { mutableStateOf(false) }
    val snapshot = state.snapshot
    if (snapshot == null || state.connectionScreen) {
        BackHandler(enabled = snapshot != null && state.connectionScreen) { model.closeConnections() }
        Surface(color = Ground) { ConnectScreen(state, model, openBrowser, Modifier.safeDrawingPadding()) }
        return
    }
    val selected = detail?.let { name -> Feature.entries.firstOrNull { it.name == name } }
    val back = rootBack(detail != null, state.destination)
    BackHandler(enabled = back != RootBack.System) {
        if (back == RootBack.Tools) detail = null else model.destination(Destination.Overview)
    }
    val route = "${state.selected?.id}:${state.destination}:$detail"
    val scroll = rememberSaveable(route, saver = LazyListState.Saver) { LazyListState() }
    ActionReviewDialog(state, model)
    OperationFeedback(state, model, openBrowser)
    if (signOut) AlertDialog(onDismissRequest = { signOut = false }, title = { Text("Disconnect from ${state.selected?.name}?") },
        text = { Text("This ends this app session. Your saved server and approved Passkey are kept; you can sign in again without registering a new key.") },
        confirmButton = { TextButton(onClick = { signOut = false; model.disconnect() }) { Text("Disconnect and sign out") } },
        dismissButton = { TextButton(onClick = { signOut = false }) { Text("Keep connected") } })
    Scaffold(containerColor = Ground,
        topBar = {
            Column(Modifier.statusBarsPadding()) {
                Row(Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 12.dp), verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    if (selected != null) IconButton(onClick = { detail = null }) { Icon(Icons.AutoMirrored.Outlined.ArrowBack, "Back to tools") } else PulseMark()
                    Column(Modifier.weight(1f)) {
                        Text(selected?.title ?: state.destination.title, style = MaterialTheme.typography.titleMedium)
                        Text(if (state.demo) "Preview server" else state.selected?.name ?: snapshot.host, color = Muted, fontSize = 13.sp)
                    }
                    TextButton(onClick = { detail = null; model.connectScreen() }) { Text("Servers") }
                    if (!state.demo) IconButton(onClick = model::refresh, enabled = state.connected) { Icon(Icons.Outlined.Refresh, "Refresh readings") }
                }
                HorizontalDivider(color = Rule)
                if (!state.demo && (!state.connected || state.readingsStale)) {
                    Row(Modifier.fillMaxWidth().padding(horizontal = 20.dp), verticalAlignment = Alignment.CenterVertically) {
                        Text(if (!state.connected) "Session ended · readings are stale" else "Connection interrupted · readings are stale", Modifier.weight(1f), color = Warning, fontSize = 13.sp)
                        TextButton(onClick = { if (state.connected) model.refresh() else model.reconnect() }) { Text(if (state.connected) "Retry" else "Sign in again") }
                    }
                }
                if (state.actionBusy || state.actionResult != null) Row(Modifier.fillMaxWidth().padding(horizontal = 20.dp), verticalAlignment = Alignment.CenterVertically) {
                    Text("${state.operationTitle} · ${if (state.actionBusy) "Running" else "Result ready"}", Modifier.weight(1f), color = Muted, fontSize = 13.sp)
                    TextButton(onClick = model::showOperation) { Text(if (state.actionBusy) "Progress" else "View result") }
                }
                if (state.diagnostics.isNotEmpty()) TextButton(onClick = { model.destination(Destination.More); detail = Feature.Commands.name }) { Text("Diagnostic running · view status") }
            }
        },
        bottomBar = {
            Column(Modifier.background(Ground).navigationBarsPadding()) {
                HorizontalDivider(color = Rule)
                Row(Modifier.fillMaxWidth().padding(horizontal = 8.dp)) {
                    Destination.entries.forEach { destination ->
                        val active = state.destination == destination
                        val icon = when (destination) {
                            Destination.Overview -> Icons.AutoMirrored.Outlined.ShowChart
                            Destination.Bandwidth -> Icons.Outlined.SwapVert
                            Destination.Activity -> Icons.AutoMirrored.Outlined.List
                            Destination.More -> Icons.Outlined.MoreHoriz
                        }
                        Column(Modifier.weight(1f).selectable(active, role = Role.Tab, onClick = { detail = null; model.destination(destination) })
                            .padding(vertical = 10.dp).heightIn(min = 48.dp), horizontalAlignment = Alignment.CenterHorizontally,
                            verticalArrangement = Arrangement.spacedBy(5.dp)) {
                            Icon(icon, null, tint = if (active) MaterialTheme.colorScheme.onSurface else Muted, modifier = Modifier.size(23.dp))
                            Text(destination.title, color = if (active) MaterialTheme.colorScheme.onSurface else Muted, fontSize = 12.sp)
                            Box(Modifier.width(30.dp).height(1.dp).background(if (active) Signal else Ground))
                        }
                    }
                }
            }
        }) { padding ->
        // One 20dp edge and 16dp section gutter; both charts use the full content width.
        LazyColumn(Modifier.fillMaxSize().padding(padding), state = scroll, contentPadding = PaddingValues(20.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp)) {
            item {
                if (state.demo) Notice("Demo mode · Sample data · Server changes are unavailable")
                else Text("Last reading ${java.text.DateFormat.getTimeInstance(java.text.DateFormat.SHORT).format(java.util.Date(snapshot.capturedAt))}", color = Muted)
            }
            state.message?.let { message -> item { Notice(message, warning = true) } }
            item {
                Column(verticalArrangement = Arrangement.spacedBy(20.dp)) {
                    if (selected != null) ManagementScreen(selected, state, model, { detail = null }, openBrowser)
                    else when (state.destination) {
                        Destination.Overview -> OverviewScreen(snapshot)
                        Destination.Bandwidth -> if (state.demo) BandwidthScreen(DemoData.traffic) else LiveBandwidth(state, model, openBrowser)
                        Destination.Activity -> if (state.demo) ActivityScreen(snapshot, DemoData.incidents) else LiveActivity(state, model)
                        Destination.More -> {
                            MoreScreen({ detail = it.name }, { detail = null; model.connectScreen() })
                            if (!state.demo) OutlinedButton(onClick = { signOut = true }, enabled = !state.busy && !state.actionBusy,
                                modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp)) { Text("Disconnect and sign out") }
                        }
                    }
                }
            }
        }
    }
}
