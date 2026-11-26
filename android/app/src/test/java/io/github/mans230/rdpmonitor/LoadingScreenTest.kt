package io.github.mans230.rdpmonitor

import android.graphics.Bitmap
import android.graphics.Canvas
import androidx.activity.ComponentActivity
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import io.github.mans230.rdpmonitor.ui.components.LoadingPage
import io.github.mans230.rdpmonitor.ui.theme.RdpTheme
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode
import java.io.File

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34], qualifiers = "w390dp-h844dp-mdpi")
@GraphicsMode(GraphicsMode.Mode.NATIVE)
class LoadingScreenTest {
    @get:Rule val ui = createAndroidComposeRule<ComponentActivity>()
    @Test fun loadingKeepsItsPurposeVisibleDuringAnimation() {
        ui.setContent { RdpTheme { LoadingPage("Connecting securely", "Preview connector") } }
        ui.mainClock.advanceTimeBy(300)
        ui.onNodeWithText("Connecting securely").assertIsDisplayed()
        ui.onNodeWithText("Preview connector").assertIsDisplayed()
        ui.onNode(hasProgressBarRangeInfo(androidx.compose.ui.semantics.ProgressBarRangeInfo.Indeterminate)).assertIsDisplayed()
        ui.runOnIdle {
            val view = ui.activity.window.decorView
            val bitmap = Bitmap.createBitmap(view.width, view.height, Bitmap.Config.ARGB_8888)
            view.draw(Canvas(bitmap))
            File("build/reports/app-journeys/390-loading.png").apply { parentFile!!.mkdirs() }.outputStream().use { bitmap.compress(Bitmap.CompressFormat.PNG, 100, it) }
        }
    }
}
