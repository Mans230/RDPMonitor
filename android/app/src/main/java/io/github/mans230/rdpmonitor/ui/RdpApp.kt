package io.github.mans230.rdpmonitor.ui

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.selection.selectable
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ShowChart
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
    val snapshot = state.snapshot
    if (snapshot == null) {
        Surface(color = Ground) { ConnectScreen(state, model, openBrowser, Modifier.safeDrawingPadding()) }
        return
    }
    val selected = detail?.let { name -> Feature.entries.firstOrNull { it.name == name } }
    BackHandler { if (detail != null) detail = null else model.connectScreen() }
    Scaffold(containerColor = Ground,
        topBar = {
            Column(Modifier.statusBarsPadding()) {
                Row(Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 12.dp), verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    PulseMark()
                    Column(Modifier.weight(1f)) {
                        Text("RDPMonitor", style = MaterialTheme.typography.titleMedium)
                        Text(if (state.demo) "Preview server" else state.selected?.name ?: snapshot.host, color = Muted, fontSize = 13.sp)
                    }
                    IconButton(onClick = { detail = null; model.connectScreen() }) { Icon(Icons.Outlined.Dns, "Server connections", tint = Muted) }
                    if (!state.demo) IconButton(onClick = model::refresh, enabled = state.connected) { Icon(Icons.Outlined.Refresh, "Refresh readings") }
                }
                HorizontalDivider(color = Rule)
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
                            Destination.Activity -> Icons.Outlined.NotificationsNone
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
        LazyColumn(Modifier.fillMaxSize().padding(padding), contentPadding = PaddingValues(20.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp)) {
            item {
                if (state.demo) Notice("Demo mode · Sample data · Server changes are unavailable")
                else Text("Last reading ${java.text.DateFormat.getTimeInstance(java.text.DateFormat.SHORT).format(java.util.Date(snapshot.capturedAt))}", color = Muted)
            }
            state.message?.let { message -> item { Notice(message, warning = true) } }
            item {
                Column(verticalArrangement = Arrangement.spacedBy(20.dp)) {
                    if (selected != null) FeatureScreen(selected, state.demo, { detail = null },
                        if (!state.demo) state.selected?.let { profile -> ({ openBrowser(profile.origin + "/") }) } else null)
                    else when (state.destination) {
                        Destination.Overview -> OverviewScreen(snapshot)
                        Destination.Bandwidth -> BandwidthScreen(if (state.demo) DemoData.traffic else null)
                        Destination.Activity -> ActivityScreen(snapshot, if (state.demo) DemoData.incidents else emptyList())
                        Destination.More -> MoreScreen({ detail = it.name }, { detail = null; model.connectScreen() })
                    }
                }
            }
        }
    }
}
