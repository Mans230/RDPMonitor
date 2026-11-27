package io.github.mans230.rdpmonitor.ui

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.LocalIndication
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.animation.core.animateDpAsState
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.snap
import androidx.compose.animation.animateColorAsState
import androidx.compose.ui.draw.drawWithContent
import androidx.compose.ui.geometry.Size
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.*
import androidx.compose.material.icons.automirrored.outlined.ArrowBack
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

@Composable fun RdpApp(model: RdpViewModel, openBrowser: (String) -> Unit,
    workspaceContent: (@Composable () -> Unit)? = null, workspaceKey: String? = null, showShell: Boolean = false,
    workspaceBack: (() -> Unit)? = null, onNavigate: () -> Unit = {}) {
    val state by model.state.collectAsStateWithLifecycle()
    var detail by rememberSaveable { mutableStateOf<String?>(null) }
    val appearance = appearanceAction()
    val snapshot = state.snapshot
    val serverWorkspace = LocalServerWorkspace.current
    val connections = { if (serverWorkspace != null && !state.demo) serverWorkspace() else model.connectScreen() }
    if (workspaceContent == null && (state.connectionScreen || snapshot == null && !showShell)) {
        BackHandler(enabled = snapshot != null && state.connectionScreen) { model.closeConnections() }
        Surface(color = Color.Transparent) { ConnectScreen(state, model, openBrowser) }
        return
    }
    val selected = detail?.let { name -> Feature.entries.firstOrNull { it.name == name } }
    val back = rootBack(detail != null, state.destination)
    BackHandler(enabled = workspaceContent == null && back != RootBack.System) {
        if (back == RootBack.Tools) detail = null else model.destination(Destination.Overview)
    }
    val route = "${state.selected?.id}:${state.destination}:$detail:$workspaceKey"
    val scroll = rememberSaveable(route, saver = LazyListState.Saver) { LazyListState() }
    val open: (Feature) -> Unit = { model.closeForm(); model.destination(Destination.More); detail = it.name }
    val directory: @Composable () -> Unit = {
        MoreScreen(open, { detail = null; connections() },
            { model.destination(Destination.Bandwidth) }, { model.destination(Destination.Activity) })
    }
    ActionReviewDialog(state, model)
    OperationFeedback(state, model, openBrowser)
    val isOverview = selected == null && state.destination == Destination.Overview
    LaunchedEffect(state.selected?.id, state.demo, state.administration, state.connected, isOverview) {
        if (isOverview && !state.demo && state.administration && state.connected)
            model.loadDocuments(listOf("/api/backup", "/api/sysinfo"))
    }
    Scaffold(containerColor = Color.Transparent, contentColor = Signal, bottomBar = {
        Box(Modifier.fillMaxWidth().navigationBarsPadding().padding(horizontal = 16.dp, vertical = 8.dp).testTag("section-navigation"), contentAlignment = Alignment.Center) {
            FunctionDock(if (workspaceContent != null) null else selected, if (workspaceContent != null) Destination.More else state.destination,
                { onNavigate(); detail = null; model.closeForm(); model.destination(Destination.Overview) }, { onNavigate(); open(it) },
                { onNavigate(); detail = null; model.closeForm(); model.destination(Destination.More) }, scrolling = scroll.isScrollInProgress)
        }
    }) { padding ->
        BoxWithConstraints(Modifier.fillMaxSize().padding(padding)) {
            val scrollingInk by animateFloatAsState(if (scroll.isScrollInProgress && LocalMotionEnabled.current) .32f else 0f, if (LocalMotionEnabled.current) tween(140) else snap(), label = "Scroll edge")
            val edgeInk = Signal
            val edge = if (maxWidth < 351.dp) 16.dp else 20.dp
            LazyColumn(Modifier.align(Alignment.TopCenter).widthIn(max = 1104.dp).fillMaxHeight().testTag("app-content").drawWithContent {
                    drawContent()
                    if (scroll.canScrollBackward) drawRect(edgeInk.copy(alpha = scrollingInk), size = Size(size.width, 1.dp.toPx()))
                }, state = scroll,
                contentPadding = PaddingValues(horizontal = edge, vertical = 20.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
                item {
                    Column {
                    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                        PulseMark()
                        Column(Modifier.weight(1f)) {
                            Text("RDPMonitor", style = MaterialTheme.typography.titleMedium)
                        }
                        val toggleTheme = LocalToggleAppearance.current
                        val darkAppearance = LocalDarkAppearance.current
                        Surface(shape = RoundedCornerShape(6.dp), color = Tray, border = BorderStroke(1.dp, Rule)) {
                            MotionIconButton(onClick = toggleTheme) { Icon(if (darkAppearance) Icons.Outlined.LightMode else Icons.Outlined.DarkMode, "Toggle theme") }
                        }
                        Surface(shape = RoundedCornerShape(6.dp), color = Tray, border = BorderStroke(1.dp, Rule)) {
                            MotionIconButton(onClick = appearance) { Icon(Icons.Outlined.Tune, "Appearance") }
                        }
                    }
                    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                        Text(if (state.demo) "Sample data" else state.selected?.name ?: snapshot?.host ?: "No server connected", Modifier.weight(1f), color = Muted, fontSize = 12.sp)
                        MotionIconButton(onClick = { detail = null; connections() }, enabled = !state.busy && !state.actionBusy) { Icon(Icons.Outlined.Dns, "Server connections") }
                        LocalAppAccount.current?.let { account -> MotionIconButton(onClick = account, enabled = !state.busy && !state.actionBusy) { Icon(Icons.Outlined.AccountCircle, "Account") } }
                        if (!state.demo) MotionIconButton(onClick = {
                            model.refresh()
                            if (isOverview && state.administration) model.loadDocuments(listOf("/api/backup", "/api/sysinfo"))
                        }, enabled = state.connected) { Icon(Icons.Outlined.Refresh, "Refresh readings") }
                    }
                    }
                }
                if (state.demo) item { Notice("Demo mode · Sample data · Server changes are unavailable") }
                else if (snapshot != null) item { Text("Last reading ${java.text.DateFormat.getTimeInstance(java.text.DateFormat.SHORT).format(java.util.Date(snapshot.capturedAt))}", color = Muted, fontSize = 12.sp) }
                if (snapshot != null && !state.demo && (!state.connected || state.readingsStale)) item {
                    Notice(if (!state.connected) "Session ended · readings are stale" else "Connection interrupted · readings are stale", true)
                    CossTextButton(onClick = { if (state.connected) model.refresh() else model.reconnect() }) { Text(if (state.connected) "Retry" else "Sign in again") }
                }
                state.message?.let { message -> item { Notice(message, true) } }
                if (workspaceContent != null) item { MotionIconButton(onClick = { workspaceBack?.invoke() ?: onNavigate() }) { Icon(Icons.AutoMirrored.Outlined.ArrowBack, "Go back") } }
                if (state.actionBusy || state.actionResult != null) item {
                    CossTextButton(onClick = model::showOperation) { Text("${state.operationTitle} · ${if (state.actionBusy) "Running — view progress" else "Result ready"}") }
                }
                if (state.diagnostics.isNotEmpty()) item { CossTextButton(onClick = { open(Feature.Diagnostics) }) { Text("Diagnostic running · view status") } }
                item {
                    Column(pageMotion(route), verticalArrangement = Arrangement.spacedBy(16.dp)) {
                        if (workspaceContent != null) workspaceContent()
                        else if (selected == null && state.destination == Destination.More) directory()
                        else if (snapshot == null) {
                            PageTitle("Server disconnected", "")
                            Notice("Choose a saved server to reconnect. No readings are displayed.")
                            CossOutlinedButton(onClick = connections) { Text("Server connections") }
                        } else when (selected) {
                            Feature.Processes -> if (state.demo) ActivityScreen(snapshot, emptyList(), processesOnly = true) else LiveActivity(state, model, processesOnly = true)
                            Feature.History -> ResourceHistory(snapshot)
                            null -> when (state.destination) {
                                Destination.Overview -> OverviewScreen(snapshot, state)
                                Destination.Bandwidth -> if (state.demo) BandwidthScreen(DemoData.traffic) else LiveBandwidth(state, model, openBrowser)
                                Destination.Activity -> if (state.demo) ActivityScreen(snapshot, DemoData.incidents) else LiveActivity(state, model)
                                Destination.More -> {
                                    directory()
                                }
                            }
                            else -> ManagementScreen(selected, state, model, { detail = null }, openBrowser, open)
                        }
                    }
                }
            }
        }
    }
}

@Composable internal fun FunctionDock(selected: Feature?, destination: Destination, overview: () -> Unit,
    open: (Feature) -> Unit, more: () -> Unit, scrolling: Boolean = false) {
    val motion = LocalMotionEnabled.current
    val easing = engineEasing()
    val dockScale by animateFloatAsState(if (scrolling && motion) .985f else 1f,
        if (motion) spring(dampingRatio = 1f, stiffness = 550f) else snap(), label = "Dock scroll response")
    BoxWithConstraints {
        val compact = maxWidth < 340.dp
        GlassSurface(Modifier.graphicsLayer { scaleX = dockScale; scaleY = dockScale }, radius = 32.dp, blur = 24.dp) {
            BoxWithConstraints(Modifier.widthIn(max = 380.dp).fillMaxWidth().padding(5.dp)) {
                val labels = listOf("Overview", "Protect", "Backups", "Processes", "More")
                val features = listOf(null, Feature.Protection, Feature.Backups, Feature.Processes, null)
                val activeIndex = when {
                    selected == null && destination == Destination.Overview -> 0
                    selected == Feature.Protection -> 1
                    selected == Feature.Backups -> 2
                    selected == Feature.Processes -> 3
                    else -> 4
                }
                val cell = maxWidth / 5
                val position by animateDpAsState(cell * activeIndex,
                    if (motion) tween(280, easing = easing) else snap(), label = "Dock selection position")
                Box(Modifier.matchParentSize()) {
                    Box(Modifier.offset { androidx.compose.ui.unit.IntOffset(position.roundToPx(), 0) }.width(cell).fillMaxHeight()
                        .background(Signal.copy(alpha = .12f), RoundedCornerShape(26.dp)).testTag("dock-indicator"))
                }
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.Center) {
                    labels.forEachIndexed { index, label ->
                        val active = index == activeIndex
                        val interaction = remember { MutableInteractionSource() }
                        val tint by animateColorAsState(if (active) Signal else Muted,
                            if (motion) tween(160) else snap(), label = "Navigation tint")
                        val lift by animateFloatAsState(if (active && motion) -1.5f else 0f,
                            if (motion) spring(dampingRatio = .8f, stiffness = 600f) else snap(), label = "Navigation icon lift")
                        val icon = when (index) { 0 -> CossIcons.Activity; 1 -> Icons.Outlined.VerifiedUser; 2 -> CossIcons.Archive; 3 -> CossIcons.ListFilter; else -> Icons.Outlined.MoreHoriz }
                        Column(Modifier.weight(1f).pressMotion(interaction)
                            .selectable(active, interactionSource = interaction, indication = LocalIndication.current, role = Role.Tab,
                                onClick = { when (index) { 0 -> overview(); 4 -> more(); else -> open(features[index]!!) } })
                            .padding(horizontal = 2.dp, vertical = 8.dp).heightIn(min = 44.dp),
                            horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(4.dp)) {
                            Icon(icon, null, Modifier.size(18.dp).graphicsLayer { translationY = lift.dp.toPx() }, tint = tint)
                            Text(if (compact && index == 3) "Tasks" else label, maxLines = 1, fontSize = 11.sp, color = tint)
                        }
                    }
                }
            }
        }
    }
}
