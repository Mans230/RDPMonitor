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

@Composable fun ActivityScreen(snapshot: Snapshot, incidents: List<Incident>, onStop: ((ProcessRow) -> Unit)? = null, processesOnly: Boolean = false) {
    var section by rememberSaveable(processesOnly) { mutableStateOf(if (processesOnly) "Processes" else "Events") }
    var query by rememberSaveable { mutableStateOf("") }
    PageTitle(if (processesOnly) "Processes" else "Activity", "Recorded server events and current process readings.")
    if (!processesOnly) Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        listOf("Events", "Processes").forEach { name ->
            TextButton(onClick = { section = name }) {
                Text(if (section == name) "$name ·" else name, color = if (section == name) Signal else Muted)
            }
        }
    }
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
    } else Section("Processes", "Share of total CPU capacity · memory in MiB/GiB") {
        if (snapshot.processes.isEmpty()) Text("No process readings received.", color = Muted)
        OutlinedTextField(query, { query = it }, label = { Text("Search process name or PID") }, modifier = Modifier.fillMaxWidth())
        snapshot.processes.filter { it.name.contains(query, true) || it.pid.toString().contains(query) }.forEachIndexed { index, process ->
            if (index > 0) HorizontalDivider(color = Rule)
            MetricRow(process.name, percent(process.cpu), "PID ${process.pid} · ${bytes(process.memoryBytes)} RAM")
            onStop?.let { stop ->
                OutlinedButton(onClick = { stop(process) }, enabled = process.pid > 4) { Text("Stop process") }
                if (process.pid <= 4) Text("Core system process · stopping is unavailable", color = Muted, style = MaterialTheme.typography.bodySmall)
            }
        }
    }
}
