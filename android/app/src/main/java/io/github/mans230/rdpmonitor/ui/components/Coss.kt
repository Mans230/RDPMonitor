package io.github.mans230.rdpmonitor.ui.components

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.material3.*
import androidx.compose.animation.animateColorAsState
import androidx.compose.runtime.Composable
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Close
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.platform.LocalView
import androidx.compose.runtime.SideEffect
import androidx.compose.runtime.remember
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.setValue
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.window.DialogWindowProvider
import androidx.compose.ui.unit.sp
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.unit.dp
import io.github.mans230.rdpmonitor.ui.theme.*

/** A coss-style popup with quiet header/footer trays and a bounded native scrolling body. */
@Composable fun CossDialog(onDismissRequest: () -> Unit, title: @Composable () -> Unit,
                          text: @Composable () -> Unit, confirmButton: @Composable () -> Unit,
                          dismissButton: (@Composable () -> Unit)? = null, description: String? = null) {
    Dialog(onDismissRequest, properties = DialogProperties(usePlatformDefaultWidth = false)) {
        val popupWindow = (LocalView.current.parent as? DialogWindowProvider)?.window
        SideEffect {
            popupWindow?.setDimAmount(.32f)
            if (android.os.Build.VERSION.SDK_INT >= 31) popupWindow?.let { window ->
                window.addFlags(android.view.WindowManager.LayoutParams.FLAG_BLUR_BEHIND)
                val attributes = window.attributes
                attributes.blurBehindRadius = 8
                window.attributes = attributes
            }
        }
        BoxWithConstraints(Modifier.fillMaxSize()) {
            val phone = maxWidth < 640.dp
            val popupMaxHeight = maxHeight - if (phone) 48.dp else 32.dp
            var measuredHeight by remember { mutableIntStateOf(0) }
            val measuredDp = with(LocalDensity.current) { measuredHeight.toDp() }
            val tabletOffset = ((maxHeight - 32.dp - measuredDp) / 4).coerceAtLeast(0.dp)
            Box(Modifier.fillMaxSize().padding(horizontal = if (phone) 0.dp else 16.dp, vertical = if (phone) 0.dp else 16.dp),
                contentAlignment = if (phone) androidx.compose.ui.Alignment.BottomCenter else androidx.compose.ui.Alignment.TopCenter) {
            Surface(Modifier.offset(y = if (phone) 0.dp else tabletOffset).then(pageMotion(Unit)).onSizeChanged { measuredHeight = it.height }.widthIn(max = 512.dp).fillMaxWidth().heightIn(max = popupMaxHeight),
                shape = RoundedCornerShape(if (phone) 0.dp else 16.dp), color = if (LocalDarkAppearance.current) androidx.compose.ui.graphics.Color(0xFF1B1B1B) else Ground, border = BorderStroke(1.dp, Rule)) {
                Column {
                    Row(Modifier.fillMaxWidth().padding(start = 24.dp, top = 8.dp, end = 8.dp, bottom = if (phone) 16.dp else 12.dp), verticalAlignment = androidx.compose.ui.Alignment.Top) {
                        Column(Modifier.weight(1f).padding(top = 16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                            ProvideTextStyle(MaterialTheme.typography.titleLarge.copy(fontSize = 20.sp, lineHeight = 22.sp, fontWeight = FontWeight.Bold), title)
                            description?.let { Text(it, color = Muted, style = MaterialTheme.typography.bodyMedium.copy(fontSize = 14.sp, lineHeight = 20.sp)) }
                        }
                        MotionIconButton(onClick = onDismissRequest, modifier = Modifier.testTag("popup-close")) { Icon(CossIcons.X, "Close", Modifier.size(18.dp)) }
                    }
                    Column(Modifier.weight(1f, fill = false).fillMaxWidth().verticalScroll(rememberScrollState()).padding(start = 24.dp, end = 24.dp, top = 4.dp, bottom = 24.dp)) { text() }
                    HorizontalDivider(color = Rule)
                    if (phone) Column(Modifier.fillMaxWidth().background(Tray).navigationBarsPadding().padding(horizontal = 24.dp, vertical = 16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        Box(Modifier.fillMaxWidth()) { confirmButton() }; dismissButton?.invoke()
                    } else Row(Modifier.fillMaxWidth().background(Tray).padding(horizontal = 24.dp, vertical = 16.dp), horizontalArrangement = Arrangement.spacedBy(8.dp, androidx.compose.ui.Alignment.End)) {
                        dismissButton?.let { Box(Modifier.weight(1f, fill = false)) { it() } }
                        Box(Modifier.weight(1f, fill = false), contentAlignment = androidx.compose.ui.Alignment.CenterEnd) { confirmButton() }
                    }
                }
            }
            }
        }
    }
}

@Composable fun CossTextButton(onClick: () -> Unit, modifier: Modifier = Modifier, enabled: Boolean = true,
                              colors: ButtonColors = ButtonDefaults.textButtonColors(), content: @Composable RowScope.() -> Unit) {
    val interaction = remember { MutableInteractionSource() }
    TextButton(onClick, modifier.pressMotion(interaction, enabled).heightIn(min = 44.dp), enabled = enabled, shape = RoundedCornerShape(6.dp), colors = colors, interactionSource = interaction, content = content)
}

@Composable fun CossButton(onClick: () -> Unit, modifier: Modifier = Modifier, enabled: Boolean = true,
                          colors: ButtonColors = ButtonDefaults.buttonColors(containerColor = Signal, contentColor = Ground), interactionSource: MutableInteractionSource? = null,
                          content: @Composable RowScope.() -> Unit) {
    val phone = LocalConfiguration.current.screenWidthDp < 640
    val interaction = interactionSource ?: remember { MutableInteractionSource() }
    Button(onClick, modifier.pressMotion(interaction, enabled).heightIn(min = if (phone) 36.dp else 32.dp), enabled = enabled, shape = RoundedCornerShape(8.dp),
        contentPadding = PaddingValues(horizontal = 11.dp), colors = colors, interactionSource = interaction) {
        ProvideTextStyle(MaterialTheme.typography.labelLarge.copy(fontSize = if (phone) 16.sp else 14.sp)) { content() }
    }
}

@Composable fun CossOutlinedButton(onClick: () -> Unit, modifier: Modifier = Modifier, enabled: Boolean = true,
                                  colors: ButtonColors = ButtonDefaults.outlinedButtonColors(contentColor = Signal), content: @Composable RowScope.() -> Unit) {
    val phone = LocalConfiguration.current.screenWidthDp < 640
    val interaction = remember { MutableInteractionSource() }
    OutlinedButton(onClick, modifier.pressMotion(interaction, enabled).heightIn(min = if (phone) 36.dp else 32.dp), enabled = enabled, shape = RoundedCornerShape(8.dp),
        contentPadding = PaddingValues(horizontal = 11.dp), border = BorderStroke(1.dp, InputRule), colors = colors, interactionSource = interaction) {
        ProvideTextStyle(MaterialTheme.typography.labelLarge.copy(fontSize = if (phone) 16.sp else 14.sp)) { content() }
    }
}

/** Native translation of coss Frame: a tinted tray, 4dp inset, independent bordered panels. */
@Composable fun CossFrame(title: String, description: String? = null, footer: (@Composable ColumnScope.() -> Unit)? = null,
                         headerActions: (@Composable () -> Unit)? = null,
                         content: @Composable ColumnScope.() -> Unit) {
    Surface(Modifier.fillMaxWidth(), shape = RoundedCornerShape(16.dp), color = Tray) {
        Column(Modifier.padding(4.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Row(Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 16.dp), verticalAlignment = androidx.compose.ui.Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(title, style = MaterialTheme.typography.titleMedium)
                description?.let { Text(it, color = Muted, style = MaterialTheme.typography.bodyMedium.copy(fontSize = 14.sp, lineHeight = 20.sp)) }
            }
            headerActions?.invoke()
            }
            content()
            footer?.let { Column(Modifier.padding(horizontal = 20.dp, vertical = 16.dp), verticalArrangement = Arrangement.spacedBy(10.dp), content = it) }
        }
    }
}

@Composable fun CossPanel(modifier: Modifier = Modifier, inset: Dp = 20.dp, content: @Composable ColumnScope.() -> Unit) {
    Surface(modifier.fillMaxWidth(), shape = RoundedCornerShape(12.dp), color = Ground, border = BorderStroke(1.dp, Rule)) {
        Column(Modifier.padding(inset), verticalArrangement = Arrangement.spacedBy(16.dp), content = content)
    }
}

@Composable fun CossSegments(labels: List<String>, selected: Int, onSelect: (Int) -> Unit, modifier: Modifier = Modifier) {
    Row(modifier.background(Tray, RoundedCornerShape(8.dp)).padding(3.dp)) {
        labels.forEachIndexed { index, label ->
            val interaction = remember { MutableInteractionSource() }
            val fill by animateColorAsState(if (selected == index) MaterialTheme.colorScheme.surfaceContainerHighest else Tray, if (LocalMotionEnabled.current) androidx.compose.animation.core.tween(160) else androidx.compose.animation.core.snap(), label = "Segment selection")
            Surface(Modifier.weight(1f).pressMotion(interaction).selectable(selected == index, interactionSource = interaction, indication = androidx.compose.foundation.LocalIndication.current, role = Role.Tab, onClick = { onSelect(index) }),
                shape = RoundedCornerShape(6.dp), color = fill) {
                Box(Modifier.padding(horizontal = 8.dp, vertical = 12.dp), contentAlignment = androidx.compose.ui.Alignment.Center) {
                    Text(label, color = if (selected == index) Signal else Muted, style = MaterialTheme.typography.labelLarge)
                }
            }
        }
    }
}

@Composable fun CossField(label: String, value: String, onValueChange: (String) -> Unit, hint: String? = null, enabled: Boolean = true,
                          singleLine: Boolean = true, modifier: Modifier = Modifier, placeholder: String? = null,
                          keyboardOptions: KeyboardOptions = KeyboardOptions.Default, visualTransformation: VisualTransformation = VisualTransformation.None,
                          labelStyle: TextStyle = MaterialTheme.typography.labelLarge) {
    var focused by remember { mutableStateOf(false) }
    Column(modifier, verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text(label, style = labelStyle)
        val phone = LocalConfiguration.current.screenWidthDp < 640
        val ink = if (enabled) Signal else Muted
        BasicTextField(value, onValueChange, modifier = Modifier.fillMaxWidth().heightIn(min = if (phone) 36.dp else 32.dp)
            .onFocusChanged { focused = it.isFocused }
            .background(if (LocalDarkAppearance.current) androidx.compose.ui.graphics.Color.White.copy(alpha = .0256f) else Ground, RoundedCornerShape(8.dp))
            .then(Modifier.semantics { contentDescription = label })
            .then(Modifier.padding(0.dp)), enabled = enabled, singleLine = singleLine,
            keyboardOptions = keyboardOptions, visualTransformation = visualTransformation, cursorBrush = SolidColor(Signal),
            textStyle = MaterialTheme.typography.bodyMedium.copy(fontSize = if (phone) 16.sp else 14.sp, color = ink),
            decorationBox = { inner ->
                Surface(shape = RoundedCornerShape(8.dp), border = BorderStroke(if (focused) 3.dp else 1.dp, if (focused) Signal.copy(alpha = .3f) else InputRule), color = androidx.compose.ui.graphics.Color.Transparent) {
                    Box(Modifier.fillMaxWidth().padding(horizontal = 11.dp, vertical = 7.dp)) {
                        if (value.isEmpty() && placeholder != null) Text(placeholder, color = Muted, maxLines = if (singleLine) 1 else Int.MAX_VALUE,
                            overflow = TextOverflow.Ellipsis, style = MaterialTheme.typography.bodyMedium.copy(fontSize = if (phone) 16.sp else 14.sp))
                        inner()
                    }
                }
            })
        hint?.let { Text(it, color = Muted, style = MaterialTheme.typography.bodySmall) }
    }
}
