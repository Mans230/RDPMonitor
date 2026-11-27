package io.github.mans230.rdpmonitor

import androidx.activity.ComponentActivity
import androidx.compose.foundation.layout.Column
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import com.airbnb.lottie.LottieCompositionFactory
import io.github.mans230.rdpmonitor.feature.more.Feature
import io.github.mans230.rdpmonitor.ui.FunctionDock
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
class MotionInteractionTest {
    @get:Rule val ui = createAndroidComposeRule<ComponentActivity>()

    @Test fun everyButtonVariantKeepsOneClickAndDisabledActionsStayDisabled() {
        var clicks = 0
        ui.setContent { RdpTheme { Column {
            CossButton({ clicks++ }) { Text("Primary") }
            CossOutlinedButton({ clicks++ }) { Text("Outline") }
            CossTextButton({ clicks++ }) { Text("Text") }
            MotionIconButton({ clicks++ }, Modifier.testTag("icon")) { Text("Icon") }
            CossButton({ clicks++ }, enabled = false) { Text("Disabled") }
        } } }
        listOf("Primary", "Outline", "Text").forEach { ui.onNodeWithText(it).performClick() }
        ui.onNodeWithTag("icon").performClick()
        ui.onNodeWithText("Disabled").assertIsNotEnabled().performTouchInput { click() }
        ui.runOnIdle { check(clicks == 4) }
        ui.onNodeWithText("Primary").performTouchInput { down(center) }
        ui.mainClock.advanceTimeBy(80)
        ui.runOnIdle { check(clicks == 4) }
        ui.onNodeWithText("Primary").performTouchInput { up() }
        ui.runOnIdle { check(clicks == 5) }
    }

    @Test fun dockSelectionMovesBetweenDestinationsAndFastTapsKeepLatestRoute() {
        var selected by mutableStateOf<Feature?>(null)
        var destination by mutableStateOf(Destination.Overview)
        ui.setContent { RdpTheme { FunctionDock(selected, destination,
            { selected = null; destination = Destination.Overview },
            { selected = it; destination = Destination.More },
            { selected = null; destination = Destination.More }) } }
        val start = ui.onNodeWithTag("dock-indicator").fetchSemanticsNode().boundsInRoot.left
        ui.mainClock.autoAdvance = false
        ui.onNodeWithText("Backups").performClick()
        ui.mainClock.advanceTimeBy(80)
        val middle = ui.onNodeWithTag("dock-indicator").fetchSemanticsNode().boundsInRoot.left
        ui.mainClock.advanceTimeBy(1000)
        val end = ui.onNodeWithTag("dock-indicator").fetchSemanticsNode().boundsInRoot.left
        check(end > start + 50f)
        check(middle > start && middle < end) { "The selection capsule must interpolate rather than jump." }
        ui.mainClock.autoAdvance = true
        listOf("Protect", "More", "Overview", "Backups").forEach { ui.onNodeWithText(it).performClick() }
        ui.runOnIdle { check(selected == Feature.Backups); check(destination == Destination.More) }
        ui.onNodeWithText("Backups").assertIsSelected()
    }

    @Test fun reducedMotionPreservesImmediateNavigation() {
        var selected by mutableStateOf<Feature?>(null)
        ui.setContent { RdpTheme { CompositionLocalProvider(LocalMotionEnabled provides false) {
            FunctionDock(selected, Destination.Overview, { selected = null }, { selected = it }, {})
        } } }
        ui.onNodeWithText("Protect").performClick()
        ui.onNodeWithText("Protect").assertIsSelected()
        ui.runOnIdle { check(selected == Feature.Protection) }
    }

    @Test fun bundledLottieParsesWithoutNetworkAndHasAnAnimatedTimeline() {
        val result = LottieCompositionFactory.fromRawResSync(ui.activity, R.raw.connection_pulse)
        val composition = checkNotNull(result.value) { result.exception.toString() }
        check(composition.duration >= 1900f)
        check(composition.layers.isNotEmpty())
        check(composition.bounds.width() == 100)
    }
}
