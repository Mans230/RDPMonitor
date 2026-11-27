package io.github.mans230.rdpmonitor.ui.components

import android.database.ContentObserver
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import androidx.compose.animation.core.*
import androidx.compose.foundation.LocalIndication
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.composed
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.*
import androidx.compose.ui.unit.dp
import com.airbnb.lottie.compose.*
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.compose.currentStateAsState
import io.github.mans230.rdpmonitor.R
import io.github.mans230.rdpmonitor.ui.theme.*

val LocalMotionEnabled = staticCompositionLocalOf { true }

/** Follow accessibility/Developer Options changes while the app is open. */
@Composable fun systemMotionEnabled(): Boolean {
    val resolver = LocalContext.current.contentResolver
    fun enabled() = Settings.Global.getFloat(resolver, Settings.Global.ANIMATOR_DURATION_SCALE, 1f) > 0f
    var value by remember(resolver) { mutableStateOf(enabled()) }
    DisposableEffect(resolver) {
        val observer = object : ContentObserver(Handler(Looper.getMainLooper())) {
            override fun onChange(selfChange: Boolean) { value = enabled() }
        }
        resolver.registerContentObserver(Settings.Global.getUriFor(Settings.Global.ANIMATOR_DURATION_SCALE), false, observer)
        onDispose { resolver.unregisterContentObserver(observer) }
    }
    return value
}

/** Drawing-only feedback: no layout shifts, extra click handlers or delayed actions. */
@Composable fun Modifier.pressMotion(interaction: MutableInteractionSource, enabled: Boolean = true): Modifier {
    val pressed by interaction.collectIsPressedAsState()
    val motion = LocalMotionEnabled.current
    val scale by animateFloatAsState(if (pressed && enabled && motion) .965f else 1f,
        if (motion) spring(dampingRatio = .78f, stiffness = 700f) else snap(), label = "Control press")
    return graphicsLayer { scaleX = scale; scaleY = scale }
}

fun Modifier.motionClickable(enabled: Boolean = true, onClickLabel: String? = null,
    role: Role? = null, onClick: () -> Unit): Modifier = composed {
    val interaction = remember { MutableInteractionSource() }
    pressMotion(interaction, enabled).clickable(interactionSource = interaction,
        indication = LocalIndication.current, enabled = enabled, onClickLabel = onClickLabel, role = role, onClick = onClick)
}

@Composable fun MotionIconButton(onClick: () -> Unit, modifier: Modifier = Modifier, enabled: Boolean = true,
    content: @Composable () -> Unit) {
    val interaction = remember { MutableInteractionSource() }
    IconButton(onClick, modifier.pressMotion(interaction, enabled), enabled = enabled,
        interactionSource = interaction, content = content)
}

/** Keep one mounted destination: outgoing screens cannot repeat data effects or accept stale taps. */
@Composable fun pageMotion(key: Any?): Modifier {
    val progress = remember { Animatable(1f) }
    val motion = LocalMotionEnabled.current
    val easing = engineEasing()
    LaunchedEffect(key, motion) {
        if (motion) { progress.snapTo(0f); progress.animateTo(1f, tween(240, easing = easing)) }
        else progress.snapTo(1f)
    }
    return Modifier.graphicsLayer { alpha = progress.value; translationY = (1 - progress.value) * 10.dp.toPx() }
}

@Composable fun MotionButton(onClick: () -> Unit, modifier: Modifier = Modifier, enabled: Boolean = true,
    colors: ButtonColors = ButtonDefaults.buttonColors(), content: @Composable RowScope.() -> Unit) {
    // CossButton is the single press-animation owner; do not double-scale onboarding CTAs.
    CossButton(onClick, modifier, enabled = enabled, colors = colors, content = content)
}

@Composable fun LoadingIndicator(label: String) {
    val composition by rememberLottieComposition(LottieCompositionSpec.RawRes(R.raw.connection_pulse))
    val lifecycle by LocalLifecycleOwner.current.lifecycle.currentStateAsState()
    val motion = LocalMotionEnabled.current && lifecycle.isAtLeast(Lifecycle.State.STARTED)
    val progress by animateLottieCompositionAsState(composition, isPlaying = motion,
        iterations = LottieConstants.IterateForever)
    Box(Modifier.size(64.dp).clearAndSetSemantics {
        testTag = if (composition != null) "lottie-loader" else "loading-fallback"
        progressBarRangeInfo = ProgressBarRangeInfo.Indeterminate
        stateDescription = label
    }, contentAlignment = Alignment.Center) {
        if (composition != null) LottieAnimation(composition, progress = { if (motion) progress else .35f }, modifier = Modifier.size(64.dp))
        else if (motion) CircularProgressIndicator(Modifier.size(38.dp), color = Signal, strokeWidth = 2.dp)
        ManimGlyph(Modifier.size(18.dp))
    }
}

@Composable fun LoadingPage(title: String, detail: String) {
    Surface(color = Ground, modifier = Modifier.fillMaxSize()) {
        Box(Modifier.fillMaxSize().padding(28.dp), contentAlignment = Alignment.Center) {
            Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(20.dp)) {
                PulseMark()
                LoadingIndicator(title)
                Text(title, style = MaterialTheme.typography.titleMedium)
                Text(detail, color = Muted, style = MaterialTheme.typography.bodyMedium)
            }
        }
    }
}
