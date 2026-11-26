package io.github.mans230.rdpmonitor.feature.more

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp
import io.github.mans230.rdpmonitor.*
import io.github.mans230.rdpmonitor.ui.components.*
import io.github.mans230.rdpmonitor.ui.theme.*
import kotlinx.serialization.json.*
import java.net.URLEncoder
import io.github.mans230.rdpmonitor.data.DemoDocuments

private val privateKeys = setOf("token", "access_token", "refresh_token", "client_secret", "password", "cookie", "csrf", "nonce", "credential_hash")
private fun label(key: String) = key.replace('_', ' ').replaceFirstChar { it.uppercase() }
private fun display(value: JsonPrimitive): String = readableValue("", value)

fun sectionDocument(feature: Feature, path: String, data: JsonElement): JsonElement {
    val root = data as? JsonObject ?: return data
    if (path == "/api/stats") return root["sessions"] ?: JsonNull
    if (path != "/api/setup") return data
    return when (feature) {
        Feature.Backups -> JsonObject(root.filterKeys { it == "backup" } + mapOf("destinations" to JsonObject((root["cloud"] as? JsonObject).orEmpty().filterKeys { it in setOf("backup_targets", "folder") })))
        Feature.Cloud -> JsonObject(root.filterKeys { it in setOf("cloud", "images", "jobs") })
        Feature.Access -> root["remote"] ?: JsonNull
        else -> data
    }
}

private fun existingValues(tool: Tool, state: AppState): Map<String, String> {
    val setup = state.documents["/api/setup"] as? JsonObject ?: return emptyMap()
    val backup = setup["backup"] as? JsonObject
    val cloud = setup["cloud"] as? JsonObject
    fun text(obj: JsonObject?, key: String) = (obj?.get(key) as? JsonPrimitive)?.contentOrNull.orEmpty()
    fun lines(obj: JsonObject?, key: String) = (obj?.get(key) as? JsonArray)?.mapNotNull { (it as? JsonPrimitive)?.content }?.joinToString("\n").orEmpty()
    if (tool.action != "setup") return emptyMap()
    return when (tool.fixed["op"]) {
        "sources" -> mapOf("paths" to lines(backup, "sources"))
        "targets" -> mapOf("image" to text(cloud, "image_target"), "backups" to lines(cloud, "backup_targets"), "folder" to text(cloud, "folder"))
        "schedule" -> {
            val schedule = backup?.get("schedule") as? JsonObject
            val mode = text(schedule, "mode").ifEmpty { "daily" }
            mapOf("mode" to mode, "enabled" to text(schedule, "enabled").ifEmpty { "false" },
                "value" to when (mode) { "interval" -> text(schedule, "interval_hours"); "times" -> lines(schedule, "times").replace('\n', ','); else -> text(schedule, "time") })
        }
        else -> emptyMap()
    }
}

@Composable fun NativeDocument(value: JsonElement, openBrowser: (String) -> Unit, onTool: ((Tool, Map<String, String>) -> Unit)? = null, depth: Int = 0) {
    when (value) {
        is JsonNull -> Text("Unavailable", color = Muted)
        is JsonPrimitive -> {
            val text = display(value)
            if (text.startsWith("https://") && !text.contains('\n')) TextButton(onClick = { openBrowser(text) }) { Text("Open sign-in link") }
            else Text(text, style = MaterialTheme.typography.bodyMedium)
        }
        is JsonArray -> {
            var visible by remember { mutableIntStateOf(20) }
            if (value.isEmpty()) Text("No entries.", color = Muted)
            value.take(visible).forEachIndexed { index, item ->
                if (index > 0) HorizontalDivider(color = Rule)
                NativeDocument(item, openBrowser, onTool, depth + 1)
            }
            if (visible < value.size) TextButton(onClick = { visible += 20 }) { Text("Show more · ${value.size - visible} remaining") }
        }
        is JsonObject -> {
            val settingKey = value["key"]?.jsonPrimitive?.contentOrNull
            if (settingKey != null && value.containsKey("type") && value.containsKey("value")) {
                Text(value["label"]?.jsonPrimitive?.content ?: label(settingKey), style = MaterialTheme.typography.bodyLarge)
                Text((value["value"] as? JsonPrimitive)?.let(::display) ?: "Unavailable", color = Muted)
                if (onTool != null) OutlinedButton(onClick = {
                    val bool = value["type"]?.jsonPrimitive?.content == "bool"
                    val tool = Tool("Change ${value["label"]?.jsonPrimitive?.content ?: settingKey}", "Save the selected monitoring setting on the server.", "settings_set", mapOf("key" to settingKey),
                        listOf(ToolField("value", "Value", options = if (bool) listOf("on", "off") else emptyList())))
                    val current = value["value"] as? JsonPrimitive
                    onTool(tool, mapOf("value" to if (bool) { if (current?.booleanOrNull == true) "on" else "off" } else current?.content.orEmpty()))
                }) { Text("Edit setting") }
            } else {
                value.entries.filter { it.key.lowercase() !in privateKeys && it.key != "png" }.forEach { (key, item) ->
                    if (item is JsonPrimitive && item !is JsonNull && item.content.length < 24 && !item.content.startsWith("https://"))
                        MetricRow(label(key), readableValue(key, item))
                    else {
                        Text(label(key), color = Muted, style = MaterialTheme.typography.labelLarge)
                        if (depth < 7) {
                            if (item is JsonPrimitive && !item.content.startsWith("https://")) Text(readableValue(key, item), style = MaterialTheme.typography.bodyMedium)
                            else NativeDocument(item, openBrowser, onTool, depth + 1)
                        } else {
                            var expand by remember { mutableStateOf(false) }
                            TextButton(onClick = { expand = !expand }) { Text(if (expand) "Collapse details" else "Expand details") }
                            if (expand) NativeDocument(item, openBrowser, onTool, 0)
                        }
                    }
                }
                if (onTool != null && value["id"] != null && value["scope"] != null && value["created"] != null) {
                    val id = value.getValue("id").jsonPrimitive.content
                    OutlinedButton(onClick = { onTool(Tool("Revoke app session", "Immediately end this app session. It must sign in again.", "mobile_revoke", mapOf("id" to id)), emptyMap()) }) { Text("Revoke app session") }
                }
                if (onTool != null && value["id"] != null && value["state"] != null && value["op"] != null) {
                    val id = value.getValue("id").jsonPrimitive.content
                    if (value["question"] is JsonPrimitive) {
                        val question = value.getValue("question").jsonPrimitive.content
                        OutlinedButton(onClick = { onTool(Tool("Answer cloud sign-in", "Send your answer to this pending server operation.", "setup", mapOf("op" to "answer", "job" to id, "question" to question), listOf(ToolField("value", "Answer", "secret"))), emptyMap()) }) { Text("Answer sign-in question") }
                    }
                    if (value["state"]?.jsonPrimitive?.content == "running") OutlinedButton(onClick = {
                        onTool(Tool("Cancel cloud sign-in", "Cancel this pending setup operation.", "setup", mapOf("op" to "cancel", "job" to id)), emptyMap())
                    }) { Text("Cancel operation") }
                }
            }
        }
    }
}

@Composable fun ManagementScreen(feature: Feature, state: AppState, model: RdpViewModel, onBack: () -> Unit, openBrowser: (String) -> Unit) {
    val documents = ToolCatalog.documents(feature)
    LaunchedEffect(feature, state.selected?.id, state.demo) { if (documents.isNotEmpty()) model.loadDocuments(documents.map { it.second }) }
    val edit: (Tool, Map<String, String>) -> Unit = model::editTool
    TextButton(onClick = onBack) { Text("Back to tools") }
    PageTitle(feature.title, feature.summary)
    if (state.demo) Notice("Demo mode. Server reads and changes are disabled.")
    else if (!state.connected) Notice("Session ended. Use Sign in again above to resume server tools.")
    else if (!state.administration) {
        Notice("This session has monitoring access only. Reconnect and approve administration access to use server tools.")
        OutlinedButton(onClick = { model.reconnect(management = true) }) { Text("Approve administration for this server") }
    }
    if (documents.isNotEmpty()) OutlinedButton(onClick = { model.loadDocuments(documents.map { it.second }) }, enabled = !state.demo && !state.documentLoading) { Text(if (state.documentLoading) "Refreshing…" else "Refresh section") }
    if (state.documentLoading) LinearProgressIndicator(Modifier.fillMaxWidth(), color = Signal)
    documents.forEach { (title, path) -> Section(title) {
        state.documentErrors[path]?.let { Notice(it, warning = true) }
        (if (state.demo) DemoDocuments.at(path) else state.documents[path])?.let { data -> NativeDocument(sectionDocument(feature, path, data), openBrowser, if (state.administration && !state.demo) edit else null) }
            ?: Text(if (state.documentLoading) "Loading server data…" else if (state.demo) "Connect a server to load this section." else "No server data received. Select Refresh to retry.", color = Muted)
    } }
    if (feature == Feature.Commands || feature == Feature.Diagnostics) Diagnostics(state, model, openBrowser)
    if (ToolCatalog.tools(feature).isNotEmpty()) Section("Actions", "Every change is reviewed before it runs on ${state.selected?.name ?: "the server"}.") {
        ToolCatalog.tools(feature).forEach { tool ->
            OutlinedButton(onClick = { edit(tool, existingValues(tool, state)) }, enabled = state.administration && !state.demo && !state.actionBusy,
                colors = ButtonDefaults.outlinedButtonColors(contentColor = if (tool.dangerous) Warning else Signal),
                modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp)) { Text((if (tool.dangerous) "Caution · " else "") + tool.title) }
        }
    }
    if (state.documentErrors.values.any { it.contains("owner", ignoreCase = true) }) Notice("These tools require the owner's approved Passkey. Ask the owner to sign in, or choose Monitoring only in Servers.")
    state.editingTool?.let { tool -> ToolForm(tool, state, model, model::closeForm) }
}

@Composable fun OperationFeedback(state: AppState, model: RdpViewModel, openBrowser: (String) -> Unit) {
    if (!state.operationVisible) return
    AlertDialog(onDismissRequest = model::hideOperation, title = { Text(state.operationTitle) }, text = {
        Column(Modifier.heightIn(max = 420.dp).verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text("Server: ${state.operationServer}", color = Muted)
            if (state.actionBusy) { LinearProgressIndicator(Modifier.fillMaxWidth()); Text("Waiting for the server. This operation will not be automatically repeated.") }
            state.actionResult?.let { NativeDocument(it, openBrowser) }
        }
    }, confirmButton = { TextButton(onClick = { if (state.actionBusy) model.hideOperation() else model.dismissOperation() }) { Text(if (state.actionBusy) "Continue in background" else "Done") } })
}

@Composable fun ActionReviewDialog(state: AppState, model: RdpViewModel) {
    state.review?.let { review ->
        AlertDialog(onDismissRequest = model::cancelReview, title = { Text(review.tool.title) }, text = {
            Column(Modifier.heightIn(max = 400.dp).verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Text("Server: ${state.selected?.name}")
                Text(review.tool.effect)
                review.tool.safeArguments(review.payload).forEach { (key, value) ->
                    Text("${label(key)}: ${(value as? JsonPrimitive)?.content ?: value.toString()}", style = MaterialTheme.typography.bodyMedium)
                }
            }
        }, confirmButton = { TextButton(onClick = model::confirmAction) { Text("Confirm and run") } }, dismissButton = { TextButton(onClick = model::cancelReview) { Text("Cancel") } })
    }
}

@Composable private fun ToolForm(tool: Tool, state: AppState, model: RdpViewModel, dismiss: () -> Unit) {
    val values = state.formValues
    var error by remember(tool) { mutableStateOf<String?>(null) }
    var browseKey by rememberSaveable { mutableStateOf<String?>(null) }
    val browseField = tool.fields.firstOrNull { it.key == browseKey }
    var browsePath by rememberSaveable { mutableStateOf("") }
    var browseOffset by rememberSaveable { mutableIntStateOf(0) }
    val browseUrl = "/api/setup/browse?path=" + URLEncoder.encode(browsePath, "UTF-8") + "&offset=$browseOffset"
    AlertDialog(onDismissRequest = dismiss, title = { Text(tool.title) }, text = {
        Column(Modifier.heightIn(max = 440.dp).verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(14.dp)) {
            Text(tool.effect, color = Muted)
            tool.visibleFields(values).forEach { field ->
                if (field.options.isNotEmpty()) {
                    var expanded by remember(field.key) { mutableStateOf(false) }
                    Box {
                        OutlinedButton(onClick = { expanded = true }, modifier = Modifier.fillMaxWidth()) { Text("${field.label}: ${values[field.key].orEmpty().ifEmpty { "Choose…" }}") }
                        DropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }) {
                            field.options.forEach { value -> DropdownMenuItem(text = { Text(value) }, onClick = { model.updateForm(field.key, value); expanded = false }) }
                        }
                    }
                } else OutlinedTextField(value = values[field.key].orEmpty(), onValueChange = { model.updateForm(field.key, it) },
                    label = { Text(field.label + if (field.optional) " (optional)" else "") }, modifier = Modifier.fillMaxWidth(),
                    singleLine = field.kind !in listOf("lines", "paths", "options"),
                    visualTransformation = if (field.kind == "secret") PasswordVisualTransformation() else VisualTransformation.None,
                    keyboardOptions = KeyboardOptions(keyboardType = if (field.kind == "int") KeyboardType.Number else if (field.kind == "secret") KeyboardType.Password else KeyboardType.Text))
                if (field.kind in listOf("path", "paths", "file")) TextButton(onClick = { browseKey = field.key; browsePath = ""; browseOffset = 0; model.loadDocuments(listOf("/api/setup/browse?path=&offset=0")) }) { Text(if (field.kind == "file") "Browse server files" else "Browse server folders") }
                val setup = state.documents["/api/setup"] as? JsonObject
                val cloud = setup?.get("cloud") as? JsonObject
                val remotes = (cloud?.get("remotes") as? JsonArray)?.mapNotNull { (it as? JsonPrimitive)?.content }
                val suggestions = when {
                    field.key == "backups" -> remotes.orEmpty()
                    field.key == "name" && tool.fixed["op"] in listOf("client", "delete") -> remotes.orEmpty().map { it.removeSuffix(":") }
                    field.key in listOf("target", "image") -> remotes.orEmpty()
                    field.key == "name" && tool.action == "restore" -> ((state.documents["/api/backup"] as? JsonObject)?.get("items") as? JsonArray)?.mapNotNull { (it as? JsonObject)?.get("name")?.jsonPrimitive?.content }.orEmpty()
                    else -> emptyList()
                }
                if (suggestions.isNotEmpty()) {
                    var choose by remember(field.key) { mutableStateOf(false) }
                    Box {
                        TextButton(onClick = { choose = true }) { Text("Choose existing ${field.label.lowercase()}") }
                        DropdownMenu(choose, { choose = false }) { suggestions.forEach { suggestion ->
                            DropdownMenuItem(text = { Text(suggestion) }, onClick = {
                                model.updateForm(field.key, if (field.kind == "lines") (values[field.key].orEmpty() + "\n" + suggestion).trim() else suggestion); choose = false
                            })
                        } }
                    }
                }
            }
            error?.let { Notice(it, warning = true) }
        }
    }, confirmButton = { TextButton(enabled = !state.actionBusy, onClick = {
        try { val payload = tool.payload(values); model.review(tool, payload); dismiss() } catch (e: Exception) { error = e.message ?: "Check the form values." }
    }) { Text("Review change") } }, dismissButton = { TextButton(onClick = dismiss) { Text("Cancel") } })
    browseField?.let { field -> AlertDialog(onDismissRequest = { browseKey = null }, title = { Text(if (field.kind == "file") "Select server file" else "Select server folder") }, text = {
        val data = state.documents[browseUrl] as? JsonObject
        Column(Modifier.heightIn(max = 360.dp).verticalScroll(rememberScrollState())) {
            Text(browsePath.ifEmpty { "Drives" }, color = Muted)
            val parent = data?.get("parent")?.jsonPrimitive?.content.orEmpty()
            if (browsePath.isNotEmpty()) TextButton(onClick = {
                browsePath = parent; browseOffset = 0
                model.loadDocuments(listOf("/api/setup/browse?path=" + URLEncoder.encode(parent, "UTF-8") + "&offset=0"))
            }) { Text("Up one level") }
            state.documentErrors[browseUrl]?.let { Text(it, color = Warning) }
            if (state.documentLoading) Text("Loading…")
            (data?.get("items") as? JsonArray)?.forEach { item ->
                val row = item.jsonObject
                val directory = row["directory"]?.jsonPrimitive?.booleanOrNull == true
                if (directory || field.kind == "file") TextButton(onClick = {
                    val selected = row.getValue("path").jsonPrimitive.content
                    if (directory) {
                        browsePath = selected; browseOffset = 0
                        model.loadDocuments(listOf("/api/setup/browse?path=" + URLEncoder.encode(browsePath, "UTF-8") + "&offset=0"))
                    } else { model.updateForm(field.key, selected); browseKey = null }
                }) { Text((if (directory) "Folder · " else "File · ") + (row["name"]?.jsonPrimitive?.content ?: "Entry")) }
            }
            if (browseOffset > 0) TextButton(onClick = { browseOffset = (browseOffset - 100).coerceAtLeast(0); model.loadDocuments(listOf("/api/setup/browse?path=" + URLEncoder.encode(browsePath, "UTF-8") + "&offset=$browseOffset")) }) { Text("Previous entries") }
            val next = data?.get("next")?.jsonPrimitive?.intOrNull
            if (next != null) TextButton(onClick = { browseOffset = next; model.loadDocuments(listOf("/api/setup/browse?path=" + URLEncoder.encode(browsePath, "UTF-8") + "&offset=$browseOffset")) }) { Text("Next entries") }
        }
    }, confirmButton = { TextButton(enabled = browsePath.isNotEmpty() && field.kind != "file", onClick = {
        model.updateForm(field.key, if (field.kind == "paths") (values[field.key].orEmpty().trim() + "\n" + browsePath).trim() else browsePath)
        browseKey = null
    }) { Text(if (field.kind == "file") "Choose a file from the list" else "Select folder") } }, dismissButton = { TextButton(onClick = { browseKey = null }) { Text("Close") } }) }
}

@Composable private fun Diagnostics(state: AppState, model: RdpViewModel, openBrowser: (String) -> Unit) {
    val selected = state.diagnosticOp
    val argument = state.diagnosticArgument
    var expanded by remember { mutableStateOf(false) }
    Section("Diagnostics") {
        Box {
            OutlinedButton(onClick = { expanded = true }) { Text(diagnosticTitle(selected)) }
            DropdownMenu(expanded, { expanded = false }) {
                listOf("diagnose", "logstats", "logs", "firewall", "netstat", "when", "ps", "bigfiles", "temp", "startup", "updates", "sysinfo", "harden", "report", "logins", "botlog", "dumps", "speedtest", "nettest").forEach { op ->
                    DropdownMenuItem(text = { Text(diagnosticTitle(op)) }, onClick = { model.diagnosticInput(op, ""); expanded = false })
                }
            }
        }
        val argumentRequired = diagnosticRequiresArgument(selected)
        Text(diagnosticHint(selected), color = Muted)
        OutlinedTextField(argument, { model.diagnosticInput(selected, it) }, label = { Text(if (argumentRequired) "Required parameter · see hint above" else "Optional parameters · see hint above") }, modifier = Modifier.fillMaxWidth())
        val path = "/api/diag?op=$selected&arg=" + URLEncoder.encode(argument, "UTF-8")
        val running = path in state.diagnostics
        Button(onClick = { model.loadDocuments(listOf(path)) }, enabled = !state.demo && state.administration && !running && (!argumentRequired || argument.isNotBlank())) { Text(if (running) "Diagnostic running…" else "Run diagnostic") }
        if (running) { LinearProgressIndicator(Modifier.fillMaxWidth()); Text("You can switch pages. This diagnostic keeps running.", color = Muted) }
        state.documentErrors[path]?.let { Notice(it, true) }
        state.documents[path]?.let { NativeDocument(it, openBrowser) }
    }
}
