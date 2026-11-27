package io.github.mans230.rdpmonitor

import android.graphics.Bitmap
import android.graphics.Canvas
import androidx.activity.ComponentActivity
import androidx.compose.foundation.layout.*
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.Modifier
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleOwner
import androidx.lifecycle.LifecycleRegistry
import androidx.lifecycle.compose.LocalLifecycleOwner
import io.github.mans230.rdpmonitor.ui.components.*
import io.github.mans230.rdpmonitor.ui.theme.RdpTheme
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34], qualifiers = "w390dp-h844dp-mdpi")
@GraphicsMode(GraphicsMode.Mode.NATIVE)
class EngineMotionTest {
    @get:Rule val ui = createAndroidComposeRule<ComponentActivity>()
    private fun capture(): Bitmap {
        lateinit var bitmap: Bitmap
        ui.runOnIdle {
            val view = ui.activity.window.decorView
            bitmap = Bitmap.createBitmap(view.width, view.height, Bitmap.Config.ARGB_8888)
            view.draw(Canvas(bitmap))
        }
        return bitmap
    }
    @Test fun generatedAssetContractsAreFiniteBoundedAndLoopWithoutJump() {
        val assets = MotionAssets.load(ui.activity.resources)
        check(assets.scene.size > 20 && assets.morph.size > 20)
        check(assets.scene.all { frame -> frame.size == assets.scene.first().size && frame.all { it.size == 4 && it.all { value -> value.isFinite() && value in 0f..1f } } })
        check(assets.scene.first() == assets.scene.last())
        check(assets.morph.all { it.size == 64 && it.all { point -> point.size == 2 && point.all { value -> value.isFinite() && value in 0f..1f } } })
        check(assets.morph.first() != assets.morph.last())
        listOf(assets.ease, assets.pulse).forEach { curve ->
            check(curve.first() == 0f && kotlin.math.abs(curve.last() - 1f) < .0001f)
            check(curve.all { it.isFinite() && it in 0f..1f })
            check(curve.toList().zipWithNext().all { (a,b) -> b >= a })
            check(sampleCurve(curve, -1f) == curve.first() && sampleCurve(curve, 2f) == curve.last())
        }
    }
    @Test fun reducedMotionArtworkRemainsVisuallyStillWhileTimeAdvances() {
        ui.setContent { RdpTheme { CompositionLocalProvider(LocalMotionEnabled provides false) {
            EngineArtwork(Modifier.fillMaxWidth().height(200.dp))
        } } }
        ui.onNodeWithTag("three-godot-artwork").assertIsDisplayed()
        val first = capture()
        ui.mainClock.advanceTimeBy(700)
        check(first.sameAs(capture())) { "Reduced motion must not keep decorative artwork running." }
    }
    @Test fun stoppedLifecycleDoesNotKeepDecorativeTimelineRunning() {
        val owner = object : LifecycleOwner { val registry = LifecycleRegistry(this); override val lifecycle: Lifecycle get() = registry }
        ui.runOnIdle { owner.registry.currentState = Lifecycle.State.RESUMED }
        ui.setContent { RdpTheme { CompositionLocalProvider(LocalLifecycleOwner provides owner) {
            EngineArtwork(Modifier.fillMaxWidth().height(200.dp))
        } } }
        ui.mainClock.advanceTimeBy(120)
        ui.runOnIdle { owner.registry.currentState = Lifecycle.State.CREATED }
        ui.mainClock.advanceTimeBy(32)
        val stopped = capture()
        ui.mainClock.advanceTimeBy(700)
        check(stopped.sameAs(capture()))
    }
}
