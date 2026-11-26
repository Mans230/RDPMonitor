package io.github.mans230.rdpmonitor.feature.activity

import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import io.github.mans230.rdpmonitor.core.model.*
import io.github.mans230.rdpmonitor.ui.components.*
import io.github.mans230.rdpmonitor.ui.theme.*

@Composable fun ActivityScreen(snapshot: Snapshot, incidents: List<Incident>, onStop: ((ProcessRow) -> Unit)? = null, processesOnly: Boolean = false, onStopMany: ((List<ProcessRow>) -> Unit)? = null) {
    var section by rememberSaveable(processesOnly) { mutableStateOf(if (processesOnly) "Processes" else "Events") }
    PageTitle(if (processesOnly) "Processes" else "Activity", "Recorded server events and current process readings.")
    if (!processesOnly) CossSegments(listOf("Events", "Processes"), if (section == "Events") 0 else 1,
        { section = if (it == 0) "Events" else "Processes" }, Modifier.fillMaxWidth())
    if (section == "Events") {
        Section("Recent activity") {
            if (incidents.isEmpty()) Text("No recorded activity was returned for this server.", color = Muted)
            incidents.forEachIndexed { i, incident ->
                if (i > 0) HorizontalDivider(color = Rule)
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                        Text(incident.title, color = if (incident.needsAttention) Warning else MaterialTheme.colorScheme.onSurface)
                        Text(incident.detail, color = Muted, style = MaterialTheme.typography.bodyMedium)
                    }
                    Text(incident.age, color = Muted, style = MaterialTheme.typography.bodyMedium)
                }
            }
        }
    } else ProcessWorkspace(snapshot, onStop, onStopMany)
}
