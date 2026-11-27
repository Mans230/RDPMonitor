package io.github.mans230.rdpmonitor.ui.components

import android.content.res.Resources
import androidx.compose.animation.core.*
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.Alignment
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.platform.LocalResources
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.compose.currentStateAsState
import io.github.mans230.rdpmonitor.R
import io.github.mans230.rdpmonitor.Destination
import io.github.mans230.rdpmonitor.feature.more.Feature
import io.github.mans230.rdpmonitor.ui.FunctionDock
import io.github.mans230.rdpmonitor.ui.theme.*
import kotlinx.serialization.json.*
import kotlin.math.*

/** Engine-generated data only; no JavaScript, Python or game runtime executes in the app. */
val LocalMotionPreview = staticCompositionLocalOf<() -> Unit> { {} }

internal data class MotionBundle(
    val scene: List<List<List<Float>>>, val ease: FloatArray,
    val pulse: FloatArray, val morph: List<List<List<Float>>>)

internal object MotionAssets {
    @Volatile private var cached: MotionBundle? = null
    fun load(resources: Resources): MotionBundle = cached ?: synchronized(this) {
        cached ?: run {
            fun read(id: Int) = resources.openRawResource(id).bufferedReader().use { Json.parseToJsonElement(it.readText()).jsonObject }
            fun frames(data: JsonObject) = data.getValue("frames").jsonArray.map { frame -> frame.jsonArray.map { point -> point.jsonArray.map { it.jsonPrimitive.float } } }
            val scene = read(R.raw.motion_scene)
            val morph = read(R.raw.motion_morph)
            val pulse = read(R.raw.motion_pulse)
            require(scene["schema"]?.jsonPrimitive?.int == 1 && morph["schema"]?.jsonPrimitive?.int == 1 && pulse["schema"]?.jsonPrimitive?.int == 1)
            MotionBundle(frames(scene), scene.getValue("ease").jsonArray.map { it.jsonPrimitive.float }.toFloatArray(),
                pulse.getValue("samples").jsonArray.map { it.jsonPrimitive.float }.toFloatArray(), frames(morph)).also { cached = it }
        }
    }
}

internal fun sampleCurve(samples: FloatArray, fraction: Float): Float {
    val position = fraction.coerceIn(0f, 1f) * (samples.size - 1)
    val first = position.toInt()
    val second = (first + 1).coerceAtMost(samples.lastIndex)
    return samples[first] + (samples[second] - samples[first]) * (position - first)
}

@Composable internal fun engineEasing(): Easing {
    val resources = LocalResources.current
    return remember(resources) { val curve = MotionAssets.load(resources).ease; Easing { sampleCurve(curve, it) } }
}

/** Decorative animations stop when hidden/backgrounded or when system animation is disabled. */
@Composable private fun ambientPhase(duration: Int): State<Float> {
    val lifecycle by LocalLifecycleOwner.current.lifecycle.currentStateAsState()
    if (!LocalMotionEnabled.current || !lifecycle.isAtLeast(Lifecycle.State.STARTED)) return rememberUpdatedState(.25f)
    val transition = rememberInfiniteTransition(label = "Decorative motion")
    return transition.animateFloat(0f, 1f, infiniteRepeatable(tween(duration, easing = LinearEasing)), label = "Asset timeline")
}

/** Three.js projected wireframe + Godot-timed network signals, painted as native vectors. */
@Composable fun EngineArtwork(modifier: Modifier = Modifier) {
    val bundle = MotionAssets.load(LocalResources.current)
    val phase = ambientPhase(6400)
    val ink = Signal; val muted = Muted; val motion = LocalMotionEnabled.current
    Canvas(modifier.testTag("three-godot-artwork")) {
        val position = phase.value * bundle.scene.lastIndex
        val index = position.toInt().coerceIn(bundle.scene.indices)
        val frame = bundle.scene[index]
        val next = bundle.scene[(index + 1).coerceAtMost(bundle.scene.lastIndex)]
        val blend = position - index
        val center = Offset(size.width * .5f, size.height * .5f)
        val nodes = listOf(Offset(size.width * .10f, size.height * .29f), Offset(size.width * .89f, size.height * .27f), Offset(size.width * .88f, size.height * .76f))
        nodes.forEachIndexed { index, node ->
            drawLine(muted.copy(alpha = .22f), node, center, 1.dp.toPx())
            drawCircle(ink.copy(alpha = .50f), 3.dp.toPx(), node, style = Stroke(1.dp.toPx()))
            if (motion) {
                val fraction = (phase.value * 2 + index / 3f) % 1f
                val travel = sampleCurve(bundle.pulse, fraction)
                val packet = node + (center - node) * travel
                drawCircle(ink.copy(alpha = .65f * sin(fraction * PI).toFloat().coerceAtLeast(0f)), 2.dp.toPx(), packet)
            }
        }
        frame.forEachIndexed { lineIndex, line ->
            fun value(component: Int) = line[component] + (next[lineIndex][component] - line[component]) * blend
            drawLine(ink.copy(alpha = .82f), Offset(value(0) * size.width, value(1) * size.height),
                Offset(value(2) * size.width, value(3) * size.height), 1.25.dp.toPx(), cap = StrokeCap.Round)
        }
    }
}

/** Manim's sampled Square-to-Circle transform; current-color native paths, not video playback. */
@Composable fun ManimGlyph(modifier: Modifier = Modifier) {
    val bundle = MotionAssets.load(LocalResources.current)
    val phase = ambientPhase(2400)
    val color = Signal
    Canvas(modifier.testTag("manim-glyph")) {
        val progress = if (phase.value < .5f) phase.value * 2 else (1 - phase.value) * 2
        val position = progress * bundle.morph.lastIndex
        val index = position.toInt().coerceIn(bundle.morph.indices)
        val frame = bundle.morph[index]
        val next = bundle.morph[(index + 1).coerceAtMost(bundle.morph.lastIndex)]
        val blend = position - index
        val path = Path()
        frame.forEachIndexed { pointIndex, point ->
            val x = (point[0] + (next[pointIndex][0] - point[0]) * blend) * size.width
            val y = (point[1] + (next[pointIndex][1] - point[1]) * blend) * size.height
            if (pointIndex == 0) path.moveTo(x, y) else path.lineTo(x, y)
        }
        path.close()
        drawPath(path, color, style = Stroke(1.25.dp.toPx()))
    }
}

/** Isolated visual review: these controls change only local preview state, never server state. */
@Composable fun MotionPreviewContent() {
    var playing by remember { mutableStateOf(true) }
    var selected by remember { mutableStateOf<Feature?>(null) }
    var destination by remember { mutableStateOf(Destination.Overview) }
    val allowed = LocalMotionEnabled.current
    CossTextButton(onClick = { playing = !playing }) { Text(if (playing) "Pause previews" else "Play previews") }
    CompositionLocalProvider(LocalMotionEnabled provides (playing && allowed)) {
        CossFrame("Server artwork", "Three.js geometry / Godot timing") {
            CossPanel { EngineArtwork(Modifier.fillMaxWidth().height(170.dp)) }
        }
        CossFrame("Loading", "Lottie orbit / Manim shape") {
            CossPanel { Box(Modifier.fillMaxWidth().height(100.dp), contentAlignment = Alignment.Center) { LoadingIndicator("Loading preview") } }
        }
        CossFrame("Navigation", "Anime.js easing / native controls") {
            CossPanel(inset = 4.dp) {
                Box(Modifier.fillMaxWidth().testTag("motion-navigation-preview")) {
                    FunctionDock(selected, destination, { selected = null; destination = Destination.Overview },
                        { selected = it; destination = Destination.More }, { selected = null; destination = Destination.More })
                }
            }
        }
    }
}
