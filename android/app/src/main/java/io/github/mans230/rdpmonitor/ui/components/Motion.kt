package io.github.mans230.rdpmonitor.ui.components

import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.unit.dp
import io.github.mans230.rdpmonitor.ui.theme.*

/** One mounted destination: transitions cannot run duplicate data-loading effects. */
@Composable fun pageMotion(key: Any?): Modifier {
    val opacity = remember { Animatable(1f) }
    LaunchedEffect(key) { opacity.snapTo(0f); opacity.animateTo(1f, tween(180)) }
    return Modifier.graphicsLayer { alpha = opacity.value; translationY = (1 - opacity.value) * 8.dp.toPx() }
}

@Composable fun MotionButton(onClick: () -> Unit, modifier: Modifier = Modifier, enabled: Boolean = true,
    colors: ButtonColors = ButtonDefaults.buttonColors(), content: @Composable RowScope.() -> Unit) {
    val interaction = remember { MutableInteractionSource() }
    val pressed by interaction.collectIsPressedAsState()
    val scale by animateFloatAsState(if (pressed) .975f else 1f, tween(100), label = "Button press")
    CossButton(onClick, modifier.graphicsLayer { scaleX = scale; scaleY = scale }, enabled = enabled, colors = colors, interactionSource = interaction, content = content)
}

@Composable fun LoadingPage(title: String, detail: String) {
    Surface(color = Ground, modifier = Modifier.fillMaxSize()) {
        Box(Modifier.fillMaxSize().padding(28.dp), contentAlignment = androidx.compose.ui.Alignment.Center) {
            Column(horizontalAlignment = androidx.compose.ui.Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(20.dp)) {
                PulseMark()
                CircularProgressIndicator(Modifier.size(32.dp), color = Signal, strokeWidth = 2.dp)
                Text(title, style = MaterialTheme.typography.titleMedium)
                Text(detail, color = Muted, style = MaterialTheme.typography.bodyMedium)
            }
        }
    }
}
