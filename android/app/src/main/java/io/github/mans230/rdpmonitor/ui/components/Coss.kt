package io.github.mans230.rdpmonitor.ui.components

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.unit.dp
import io.github.mans230.rdpmonitor.ui.theme.*

/** A coss-style popup with quiet header/footer trays and a bounded native scrolling body. */
@Composable fun CossDialog(onDismissRequest: () -> Unit, title: @Composable () -> Unit,
                          text: @Composable () -> Unit, confirmButton: @Composable () -> Unit,
                          dismissButton: (@Composable () -> Unit)? = null) {
    Dialog(onDismissRequest, properties = DialogProperties(usePlatformDefaultWidth = false)) {
        BoxWithConstraints(Modifier.fillMaxSize().padding(20.dp), contentAlignment = androidx.compose.ui.Alignment.Center) {
            Surface(Modifier.widthIn(max = 520.dp).fillMaxWidth().heightIn(max = maxHeight * .9f),
                shape = RoundedCornerShape(12.dp), color = Tray, border = BorderStroke(1.dp, Rule)) {
                Column {
                    Box(Modifier.fillMaxWidth().padding(20.dp)) { ProvideTextStyle(MaterialTheme.typography.titleMedium, title) }
                    Column(Modifier.weight(1f, fill = false).fillMaxWidth().background(Ground).verticalScroll(rememberScrollState()).padding(20.dp)) { text() }
                    Row(Modifier.fillMaxWidth().padding(16.dp), horizontalArrangement = Arrangement.spacedBy(8.dp, androidx.compose.ui.Alignment.End), verticalAlignment = androidx.compose.ui.Alignment.CenterVertically) {
                        dismissButton?.let { Box(Modifier.weight(1f, fill = false), contentAlignment = androidx.compose.ui.Alignment.CenterEnd) { it() } }
                        Box(Modifier.weight(1f, fill = false), contentAlignment = androidx.compose.ui.Alignment.CenterEnd) { confirmButton() }
                    }
                }
            }
        }
    }
}

@Composable fun CossTextButton(onClick: () -> Unit, modifier: Modifier = Modifier, enabled: Boolean = true,
                              colors: ButtonColors = ButtonDefaults.textButtonColors(), content: @Composable RowScope.() -> Unit) {
    TextButton(onClick, modifier.heightIn(min = 44.dp), enabled = enabled, shape = RoundedCornerShape(6.dp), colors = colors, content = content)
}

@Composable fun CossButton(onClick: () -> Unit, modifier: Modifier = Modifier, enabled: Boolean = true,
                          colors: ButtonColors = ButtonDefaults.buttonColors(), interactionSource: MutableInteractionSource? = null,
                          content: @Composable RowScope.() -> Unit) {
    Button(onClick, modifier.heightIn(min = 44.dp), enabled = enabled, shape = RoundedCornerShape(6.dp),
        colors = colors, interactionSource = interactionSource, content = content)
}

@Composable fun CossOutlinedButton(onClick: () -> Unit, modifier: Modifier = Modifier, enabled: Boolean = true,
                                  colors: ButtonColors = ButtonDefaults.outlinedButtonColors(), content: @Composable RowScope.() -> Unit) {
    OutlinedButton(onClick, modifier.heightIn(min = 44.dp), enabled = enabled, shape = RoundedCornerShape(6.dp),
        border = BorderStroke(1.dp, Rule), colors = colors, content = content)
}

/** Native translation of coss Frame: a tinted tray, 4dp inset, independent bordered panels. */
@Composable fun CossFrame(title: String, description: String? = null, footer: (@Composable ColumnScope.() -> Unit)? = null,
                         content: @Composable ColumnScope.() -> Unit) {
    Surface(Modifier.fillMaxWidth(), shape = RoundedCornerShape(16.dp), color = Tray) {
        Column(Modifier.padding(4.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Column(Modifier.padding(horizontal = 16.dp, vertical = 12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text(title, style = MaterialTheme.typography.titleMedium)
                description?.let { Text(it, color = Muted, style = MaterialTheme.typography.bodySmall) }
            }
            content()
            footer?.let { Column(Modifier.padding(horizontal = 16.dp, vertical = 12.dp), verticalArrangement = Arrangement.spacedBy(10.dp), content = it) }
        }
    }
}

@Composable fun CossPanel(modifier: Modifier = Modifier, content: @Composable ColumnScope.() -> Unit) {
    Surface(modifier.fillMaxWidth(), shape = RoundedCornerShape(12.dp), color = Ground, border = BorderStroke(1.dp, Rule)) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(16.dp), content = content)
    }
}

@Composable fun CossSegments(labels: List<String>, selected: Int, onSelect: (Int) -> Unit, modifier: Modifier = Modifier) {
    Row(modifier.background(Tray, RoundedCornerShape(8.dp)).padding(3.dp)) {
        labels.forEachIndexed { index, label ->
            Surface(Modifier.weight(1f).selectable(selected == index, role = Role.Tab, onClick = { onSelect(index) }),
                shape = RoundedCornerShape(6.dp), color = if (selected == index) MaterialTheme.colorScheme.surfaceContainerHighest else Tray) {
                Box(Modifier.padding(horizontal = 8.dp, vertical = 12.dp), contentAlignment = androidx.compose.ui.Alignment.Center) {
                    Text(label, color = if (selected == index) Signal else Muted, style = MaterialTheme.typography.labelLarge)
                }
            }
        }
    }
}

@Composable fun CossField(label: String, value: String, onValueChange: (String) -> Unit, hint: String? = null, enabled: Boolean = true,
                          singleLine: Boolean = true, modifier: Modifier = Modifier, placeholder: String? = null,
                          keyboardOptions: KeyboardOptions = KeyboardOptions.Default, visualTransformation: VisualTransformation = VisualTransformation.None) {
    Column(modifier, verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text(label, style = MaterialTheme.typography.labelLarge)
        OutlinedTextField(value, onValueChange, modifier = Modifier.fillMaxWidth().semantics { contentDescription = label }, enabled = enabled, singleLine = singleLine,
            placeholder = { if (placeholder != null) Text(placeholder) }, keyboardOptions = keyboardOptions, visualTransformation = visualTransformation,
            shape = RoundedCornerShape(6.dp), textStyle = MaterialTheme.typography.bodyMedium)
        hint?.let { Text(it, color = Muted, style = MaterialTheme.typography.bodySmall) }
    }
}
