package io.github.mans230.rdpmonitor.ui

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.LocalIndication
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import io.github.mans230.rdpmonitor.*
import io.github.mans230.rdpmonitor.data.DemoData
import io.github.mans230.rdpmonitor.feature.activity.ActivityScreen
import io.github.mans230.rdpmonitor.feature.bandwidth.BandwidthScreen
import io.github.mans230.rdpmonitor.feature.connect.ConnectScreen
import io.github.mans230.rdpmonitor.feature.more.*
import io.github.mans230.rdpmonitor.feature.overview.*
import io.github.mans230.rdpmonitor.ui.components.*
import io.github.mans230.rdpmonitor.ui.theme.*

@Composable fun RdpApp(model: RdpViewModel, openBrowser: (String) -> Unit) {
    val state by model.state.collectAsStateWithLifecycle()
    var detail by rememberSaveable { mutableStateOf<String?>(null) }
    var signOut by rememberSaveable { mutableStateOf(false) }
    val appearance = appearanceAction()
    val snapshot = state.snapshot
    if (snapshot == null || state.connectionScreen) {
        BackHandler(enabled = snapshot != null && state.connectionScreen) { model.closeConnections() }
        Surface(color = Color.Transparent) { ConnectScreen(state, model, openBrowser, Modifier.safeDrawingPadding()) }
        return
    }
    val selected = detail?.let { name -> Feature.entries.firstOrNull { it.name == name } }
    val back = rootBack(detail != null, state.destination)
    BackHandler(enabled = back != RootBack.System) {
        if (back == RootBack.Tools) detail = null else model.destination(Destination.Overview)
    }
    val route = "${state.selected?.id}:${state.destination}:$detail"
    val scroll = rememberSaveable(route, saver = LazyListState.Saver) { LazyListState() }
    val open: (Feature) -> Unit = { model.closeForm(); model.destination(Destination.More); detail = it.name }
    ActionReviewDialog(state, model)
    OperationFeedback(state, model, openBrowser)
    if (signOut) AlertDialog(onDismissRequest = { signOut = false }, title = { Text("Disconnect from ${state.selected?.name}?") },
        text = { Text("This ends this app session. Your saved server and approved Passkey are kept; you can sign in again without registering a new key.") },
        confirmButton = { TextButton(onClick = { signOut = false; model.disconnect() }) { Text("Disconnect and sign out") } },
        dismissButton = { TextButton(onClick = { signOut = false }) { Text("Keep connected") } })
    Scaffold(containerColor = Color.Transparent, contentColor = Signal) { padding ->
        BoxWithConstraints(Modifier.fillMaxSize().padding(padding).navigationBarsPadding()) {
            val edge = if (maxWidth < 351.dp) 16.dp else 20.dp
            LazyColumn(Modifier.align(Alignment.TopCenter).widthIn(max = 1104.dp).fillMaxHeight().testTag("app-content"), state = scroll,
                contentPadding = PaddingValues(horizontal = edge, vertical = 20.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
                item {
                    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                        PulseMark()
                        Column(Modifier.weight(1f)) {
                            Text("RDPMonitor", style = MaterialTheme.typography.titleMedium)
                            Text(if (state.demo) "Sample data" else state.selected?.name ?: snapshot.host, color = Muted, fontSize = 12.sp)
                        }
                        IconButton(onClick = appearance) { Icon(Icons.Outlined.Tune, "Appearance") }
                        IconButton(onClick = { detail = null; model.connectScreen() }) { Icon(Icons.Outlined.Dns, "Server connections") }
                        if (!state.demo) IconButton(onClick = model::refresh, enabled = state.connected) { Icon(Icons.Outlined.Refresh, "Refresh readings") }
                    }
                }
                if (state.demo) item { Notice("Demo mode · Sample data · Server changes are unavailable") }
                else item { Text("Last reading ${java.text.DateFormat.getTimeInstance(java.text.DateFormat.SHORT).format(java.util.Date(snapshot.capturedAt))}", color = Muted, fontSize = 12.sp) }
                if (!state.demo && (!state.connected || state.readingsStale)) item {
                    Notice(if (!state.connected) "Session ended · readings are stale" else "Connection interrupted · readings are stale", true)
                    TextButton(onClick = { if (state.connected) model.refresh() else model.reconnect() }) { Text(if (state.connected) "Retry" else "Sign in again") }
                }
                state.message?.let { message -> item { Notice(message, true) } }
                if (state.actionBusy || state.actionResult != null) item {
                    TextButton(onClick = model::showOperation) { Text("${state.operationTitle} · ${if (state.actionBusy) "Running — view progress" else "Result ready"}") }
                }
                if (state.diagnostics.isNotEmpty()) item { TextButton(onClick = { open(Feature.Diagnostics) }) { Text("Diagnostic running · view status") } }
                item { Column(verticalArrangement = Arrangement.spacedBy(16.dp)) { OverviewScreen(snapshot) } }
                item {
                    Box(Modifier.fillMaxWidth().padding(vertical = 12.dp), contentAlignment = Alignment.Center) {
                        FunctionDock(selected, state.destination, { detail = null; model.closeForm(); model.destination(Destination.Overview) }, open,
                            { detail = null; model.closeForm(); model.destination(Destination.More) })
                    }
                }
                item {
                    Column(pageMotion(route), verticalArrangement = Arrangement.spacedBy(16.dp)) {
                        when (selected) {
                            Feature.Processes -> if (state.demo) ActivityScreen(snapshot, emptyList(), processesOnly = true) else LiveActivity(state, model, processesOnly = true)
                            Feature.History -> ResourceHistory(snapshot)
                            null -> when (state.destination) {
                                Destination.Overview -> FunctionBoard(state, model, open)
                                Destination.Bandwidth -> if (state.demo) BandwidthScreen(DemoData.traffic) else LiveBandwidth(state, model, openBrowser)
                                Destination.Activity -> if (state.demo) ActivityScreen(snapshot, DemoData.incidents) else LiveActivity(state, model)
                                Destination.More -> {
                                    MoreScreen(open, { detail = null; model.connectScreen() })
                                    OutlinedButton(onClick = { model.destination(Destination.Bandwidth) }, modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp)) { Text("Bandwidth · recorded usage & billing window") }
                                    OutlinedButton(onClick = { model.destination(Destination.Activity) }, modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp)) { Text("Activity · recorded events") }
                                    if (!state.demo) OutlinedButton(onClick = { signOut = true }, enabled = !state.busy && !state.actionBusy,
                                        modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp)) { Text("Disconnect and sign out") }
                                }
                            }
                            else -> ManagementScreen(selected, state, model, { detail = null }, openBrowser)
                        }
                    }
                }
            }
        }
    }
}

@Composable private fun FunctionDock(selected: Feature?, destination: Destination, overview: () -> Unit, open: (Feature) -> Unit, more: () -> Unit) {
    // In the scroll flow: it reserves its own height and never covers a control or chart.
    GlassSurface(radius = 32.dp, blur = 24.dp) {
        Row(Modifier.widthIn(max = 380.dp).padding(5.dp), horizontalArrangement = Arrangement.Center) {
            val labels = listOf("Overview", "Protect", "Backups", "Processes", "More")
            val features = listOf(null, Feature.Protection, Feature.Backups, Feature.Processes, null)
            labels.forEachIndexed { index, label ->
                val interaction = remember { MutableInteractionSource() }
                val pressed by interaction.collectIsPressedAsState()
                val scale by animateFloatAsState(if (pressed) .96f else 1f, tween(100), label = "Navigation press")
                val active = when (index) {
                    0 -> selected == null && destination == Destination.Overview
                    4 -> selected !in listOf(Feature.Protection, Feature.Backups, Feature.Processes) && !(selected == null && destination == Destination.Overview)
                    else -> selected == features[index]
                }
                val icon = when (index) { 0 -> Icons.Outlined.Home; 1 -> Icons.Outlined.VerifiedUser; 2 -> Icons.Outlined.Inventory2; 3 -> Icons.Outlined.BarChart; else -> Icons.Outlined.MoreHoriz }
                Column(Modifier.weight(1f).graphicsLayer { scaleX = scale; scaleY = scale }.background(if (active) Color.White.copy(alpha = .10f) else Color.Transparent, RoundedCornerShape(26.dp))
                    .selectable(active, interactionSource = interaction, indication = LocalIndication.current, role = Role.Tab, onClick = { when (index) { 0 -> overview(); 4 -> more(); else -> open(features[index]!!) } })
                    .padding(horizontal = 2.dp, vertical = 8.dp).heightIn(min = 44.dp), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Icon(icon, null, Modifier.size(18.dp), tint = if (active) Signal else Muted)
                    Text(label, fontSize = 11.sp, color = if (active) Signal else Muted)
                }
            }
        }
    }
}
