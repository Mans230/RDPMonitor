package io.github.mans230.rdpmonitor.feature.more

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.material3.*
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.*
import androidx.compose.material.icons.automirrored.outlined.ArrowForward
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp
import java.time.LocalTime
import java.time.format.DateTimeFormatter
import java.util.Locale
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.unit.dp
import io.github.mans230.rdpmonitor.ui.components.*
import io.github.mans230.rdpmonitor.ui.theme.*
import kotlinx.serialization.json.*

internal fun validBackupSchedule(mode: String, value: String): Boolean {
    if (mode == "interval") return value.toIntOrNull() in 1..168
    if (mode !in setOf("daily", "times")) return false
    val times = value.split(',').map(String::trim)
    return times.size in 1..(if (mode == "daily") 1 else 24) && times.all { Regex("(?:[01]\\d|2[0-3]):[0-5]\\d").matches(it) }
}

/** Uses the existing setup/prepare/confirm API. Drafts never silently change server policy. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable internal fun BackupWorkspace(status: JsonElement?, setup: JsonElement?, canEdit: Boolean,
                                         onReview: (Tool, JsonObject) -> Unit, onEditSources: () -> Unit, onCloud: () -> Unit = {}) {
    val details = backupDetails(status, setup)
    val schedule = setup.obj()?.get("backup").obj()?.get("schedule").obj()
    val modes = listOf("daily", "interval", "times")
    var mode by remember(setup) { mutableStateOf(schedule.text("mode") ?: "daily") }
    var value by remember(setup) { mutableStateOf(when (mode) {
        "interval" -> schedule.text("interval_hours").orEmpty()
        "times" -> (schedule?.get("times") as? JsonArray).orEmpty().mapNotNull { (it as? JsonPrimitive)?.contentOrNull }.joinToString(", ")
        else -> schedule.text("time").orEmpty()
    }) }
    var enabled by remember(setup) { mutableStateOf(schedule.flag("enabled")) }
    var selectedSources by remember(setup) { mutableStateOf(details.sources.orEmpty().toSet()) }
    var inspected by remember { mutableStateOf<ArchiveDetail?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var showTime by remember { mutableStateOf(false) }
    var retentionMenu by remember { mutableStateOf(false) }
    var advanced by remember { mutableStateOf(false) }
    val backup = setup.obj()?.get("backup").obj()
    val retentionEditable = backup.flag("retention_editable") == true
    var retention by remember(status, setup) { mutableStateOf(backup.count("keep_local_copies") ?: status.obj()?.get("settings").obj().count("keep_local_copies")) }
    val scheduleTool = ToolCatalog.tools(Feature.Backups).first { it.fixed["op"] == "schedule" }
    CossFrame("Backup policy", "Set when it runs and how much to keep.", footer = {
        error?.let { Notice(it, true) }
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(12.dp), verticalAlignment = Alignment.CenterVertically) {
            Text("Changes need review.", Modifier.weight(1f), color = Muted, style = MaterialTheme.typography.bodySmall)
            CossButton(onClick = {
                if (enabled == null || !validBackupSchedule(mode, value)) error = "Choose a valid schedule before reviewing."
                else {
                    val values = mutableMapOf("mode" to mode, "value" to value, "enabled" to enabled.toString())
                    if (retentionEditable) retention?.let { values["keep_local_copies"] = it.toString() }
                    error = null; onReview(scheduleTool, scheduleTool.payload(values))
                }
            }, enabled = canEdit && setup != null) { Text("Review changes"); Spacer(Modifier.width(8.dp)); Icon(CossIcons.ArrowRight, null, Modifier.size(18.dp)) }
        }
        CossTextButton(onClick = { advanced = !advanced }) { Text(if (advanced) "Fewer schedule options" else "More schedule options") }
        if (advanced) {
            if (canEdit) CossSegments(listOf("Daily", "Interval", "Times"), modes.indexOf(mode), { mode = modes[it]; value = "" }, Modifier.fillMaxWidth())
            Text(details.scheduleNote, color = Muted, style = MaterialTheme.typography.bodySmall)
        }
    }) {
        CossPanel {
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Text("Automatic backups", style = MaterialTheme.typography.labelLarge)
                    Text(if (mode == "daily") "Create a recovery point every day." else "Create recovery points on the saved schedule.", color = Muted, style = MaterialTheme.typography.bodySmall)
                }
                Switch(enabled == true, { enabled = it }, enabled = canEdit && setup != null)
            }
        }
        CossPanel {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(if (mode == "daily") "Scheduled time" else "Backup schedule", style = MaterialTheme.typography.labelLarge)
                if (mode == "daily") CossOutlinedButton(onClick = { showTime = true }, enabled = canEdit, modifier = Modifier.fillMaxWidth()) {
                    Text(runCatching { LocalTime.parse(value).format(DateTimeFormatter.ofPattern("h:mm a", Locale.US)) }.getOrDefault("Time unavailable"), Modifier.weight(1f), textAlign = TextAlign.Start)
                    Icon(CossIcons.Clock, null, Modifier.size(18.dp))
                } else CossField(if (mode == "interval") "Interval hours" else "Scheduled times", value, { value = it }, enabled = canEdit)
                Text("Uses the server's time zone.", color = Muted, style = MaterialTheme.typography.bodySmall)
            }
            Spacer(Modifier.height(8.dp))
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("Local retention", style = MaterialTheme.typography.labelLarge)
                Box {
                    CossOutlinedButton(onClick = { retentionMenu = true }, enabled = canEdit && retentionEditable, modifier = Modifier.fillMaxWidth().testTag("retention-control")) {
                        Text(retention?.let { "$it copies maximum" } ?: "Retention unavailable", Modifier.weight(1f), textAlign = TextAlign.Start)
                        Icon(Icons.Outlined.UnfoldMore, null, Modifier.size(18.dp))
                    }
                    DropdownMenu(retentionMenu, { retentionMenu = false }) {
                        listOf(3L, 7L, 14L, 30L).forEach { copies -> DropdownMenuItem(text = { Text("$copies copies maximum") }, onClick = { retention = copies; retentionMenu = false }) }
                    }
                }
                Text(details.archives?.size?.let { "$it ${if (it == 1) "archive exists" else "archives exist"} now. This sets the maximum." } ?: "Archive count unavailable. This sets the maximum.", color = Muted, style = MaterialTheme.typography.bodySmall)
                if (!retentionEditable && !canEdit) Text("Read-only server policy.", color = Muted, style = MaterialTheme.typography.bodySmall)
                else if (!retentionEditable) Text("Update the server suite to change retention here.", color = Muted, style = MaterialTheme.typography.bodySmall)
            }
        }
    }
    CossFrame("Source folders", "Included in the next manual backup.", footer = {
        CossOutlinedButton(onClick = onEditSources, enabled = canEdit) { Text("Add or edit server folders") }
        if (selectedSources != details.sources.orEmpty().toSet()) {
        CossOutlinedButton(onClick = {
            val tool = ToolCatalog.tools(Feature.Backups).first { it.fixed["op"] == "sources" }
            onReview(tool, tool.payload(mapOf("paths" to details.sources.orEmpty().filter { it in selectedSources }.joinToString("\n"))))
        }, enabled = canEdit && selectedSources.isNotEmpty() && selectedSources != details.sources.orEmpty().toSet(), modifier = Modifier.fillMaxWidth()) { Text("Review source changes") }
        Text("Save the source selection first. Manual backups use saved folders.", color = Muted, style = MaterialTheme.typography.bodySmall)
        }
        CossOutlinedButton(onClick = {
            val tool = ToolCatalog.tools(Feature.Backups).first { it.action == "backup_now" }; onReview(tool, tool.payload(emptyMap()))
        }, enabled = canEdit && !details.sources.isNullOrEmpty() && selectedSources == details.sources.toSet(), modifier = Modifier.fillMaxWidth()) { Text("Back up selected folders"); Spacer(Modifier.width(8.dp)); Icon(CossIcons.Archive, null, Modifier.size(18.dp)) }
    }) {
        CossPanel {
            if (details.sources.isNullOrEmpty()) Text(if (details.sources == null) "Source list unavailable." else "No source folders configured.", color = Muted)
            LazyColumn(Modifier.fillMaxWidth().heightIn(max = 300.dp)) { itemsIndexed(details.sources.orEmpty()) { index, path ->
                Row(Modifier.fillMaxWidth().clickable(enabled = canEdit) {
                    selectedSources = if (path in selectedSources) selectedSources - path else selectedSources + path
                }, verticalAlignment = Alignment.CenterVertically) {
                    Checkbox(path in selectedSources, { checked -> selectedSources = if (checked) selectedSources + path else selectedSources - path }, enabled = canEdit, modifier = Modifier.testTag("backup-source-$index"))
                    Icon(CossIcons.Folder, null, Modifier.size(17.dp), tint = Muted)
                    Spacer(Modifier.width(10.dp))
                    Text(path, Modifier.weight(1f), style = MaterialTheme.typography.bodyMedium)
                }
            } }

        }
    }
    CossFrame("Local archives", details.archives?.let { archives ->
        val sizes = archives.map { it.raw.count("size") }
        val total = if (sizes.all { it != null }) sizes.filterNotNull().fold(java.math.BigInteger.ZERO) { sum, n -> sum + java.math.BigInteger.valueOf(n) } else null
        "${archives.size} ${if (archives.size == 1) "archive" else "archives"}${total?.takeIf { it.bitLength() < 63 }?.let { " \u00b7 ${detailBytes(it.toLong())} stored" }.orEmpty()}"
    } ?: "Archive list unavailable") {
        CossPanel {
            if (details.archives?.isEmpty() == true) Text("No local archives were reported.", color = Muted)
            LazyColumn(Modifier.fillMaxWidth().heightIn(max = 320.dp)) { itemsIndexed(details.archives.orEmpty()) { index, archive ->
                if (index > 0) HorizontalDivider(color = Rule)
                Row(Modifier.fillMaxWidth().heightIn(min = 50.dp).clickable { inspected = archive }.testTag("archive-$index"),
                    horizontalArrangement = Arrangement.spacedBy(12.dp), verticalAlignment = Alignment.CenterVertically) {
                    Icon(CossIcons.FileArchive, null, Modifier.size(21.dp), tint = Muted)
                    Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(5.dp)) {
                        Text(archive.name, style = MaterialTheme.typography.bodyMedium.copy(fontWeight = FontWeight.Medium))
                        Text(archive.modified, color = Muted, style = MaterialTheme.typography.bodySmall.copy(fontSize = 11.sp))
                    }
                    Icon(CossIcons.ArrowRight, null, Modifier.size(17.dp), tint = Muted)
                }
            } }
        }
    }
    CossFrame("Latest backup result", "Latest-run file count is separate from stored archive count.", footer = {
        Text("Uses the server's configured restore verification drill.", color = Muted, style = MaterialTheme.typography.bodySmall)
        CossOutlinedButton(onClick = { val tool = ToolCatalog.tools(Feature.Backups).first { it.action == "drill" }; onReview(tool, tool.payload(emptyMap())) }, enabled = canEdit) { Text("Restore verification drill") }
    }) {
        CossPanel {
            Text(details.result, style = MaterialTheme.typography.titleMedium)
            MetricRow("Files processed in the latest run", details.files)
            Text(details.resultNote, color = Muted, style = MaterialTheme.typography.bodySmall)
            MetricRow("Backup activity", details.activity); MetricRow("Backup engine", details.engine)
        }
    }
    CossFrame("Cloud destinations") { CossPanel {
        Text(details.remotes?.joinToString("\n")?.ifEmpty { "No cloud remotes configured" } ?: "Cloud destinations unavailable", color = Muted)
        Text(details.folder, color = Muted, style = MaterialTheme.typography.bodySmall)
        DirectoryRow("Cloud & images", onClick = onCloud)
    } }
    inspected?.let { archive -> CossDialog(onDismissRequest = { inspected = null }, title = { Text(archive.name) },
        description = "Compressed local archive metadata", text = {
        val rows = listOf("Size" to archive.size,
            "Exact bytes" to (archive.raw.count("size")?.let { String.format(Locale.US, "%,d", it) } ?: "Unavailable"),
            "Modified" to archive.modified.removeSuffix(" \u00b7 device time"), "Time display" to "Device local time")
        rows.forEachIndexed { index, (label, data) ->
            if (index > 0) HorizontalDivider(color = Rule)
            Row(Modifier.fillMaxWidth().padding(vertical = 14.dp), horizontalArrangement = Arrangement.spacedBy(24.dp)) {
                Text(label, Modifier.weight(.35f), color = Muted, style = MaterialTheme.typography.bodyMedium)
                Text(data, Modifier.weight(.65f), textAlign = TextAlign.End, style = MaterialTheme.typography.bodyMedium)
            }
        }
        CossOutlinedButton(onClick = {
            val tool = ToolCatalog.tools(Feature.Backups).first { it.action == "restore" }
            inspected = null; onReview(tool, tool.payload(mapOf("name" to archive.name)))
        }, enabled = canEdit, modifier = Modifier.fillMaxWidth()) { Text("Restore ${archive.name}") }
    }, confirmButton = { CossOutlinedButton(onClick = { inspected = null }, modifier = Modifier.fillMaxWidth()) { Text("Done") } }) }
    if (showTime) {
        val time = runCatching { LocalTime.parse(value) }.getOrDefault(LocalTime.MIDNIGHT)
        val picker = rememberTimePickerState(time.hour, time.minute, is24Hour = false)
        CossDialog(onDismissRequest = { showTime = false }, title = { Text("Scheduled time") }, description = "Uses the server's time zone.", text = { TimeInput(picker) },
            confirmButton = { CossButton(onClick = { value = String.format(Locale.US, "%02d:%02d", picker.hour, picker.minute); showTime = false }, modifier = Modifier.fillMaxWidth()) { Text("Done") } },
            dismissButton = { CossOutlinedButton(onClick = { showTime = false }, modifier = Modifier.fillMaxWidth()) { Text("Cancel") } })
    }
}
