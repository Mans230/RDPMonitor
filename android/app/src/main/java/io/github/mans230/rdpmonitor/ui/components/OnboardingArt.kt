package io.github.mans230.rdpmonitor.ui.components

import androidx.compose.runtime.*
import androidx.compose.ui.graphics.*
import androidx.compose.ui.graphics.vector.*
import androidx.compose.ui.unit.dp
import io.github.mans230.rdpmonitor.ui.theme.*

/** Exact vector paths from the approved onboarding reference, with its theme-dependent materials. */
@Composable fun serverArtwork(): ImageVector {
    val dark = LocalDarkAppearance.current
    val ground = Ground; val ink = Signal
    return remember(dark, ground, ink) {
        val line = if (dark) Color(0xFF454545) else Color(0xFFDEDEDE)
        val fillColor = if (dark) Color(0xFF202020) else Color(0xFFF7F7F7)
        ImageVector.Builder("Server network", 320.dp, 240.dp, 320f, 240f).apply {
        addPath(addPathNodes("M160 155v35m0 0H75v18m85-18h85v18"), fill = null, stroke = SolidColor(line), strokeLineWidth = 1.5f, strokeLineCap = StrokeCap.Butt)
        addPath(addPathNodes("M70.0 29.0H250.0A18.0 18.0 0 0 1 268.0 47.0V137.0A18.0 18.0 0 0 1 250.0 155.0H70.0A18.0 18.0 0 0 1 52.0 137.0V47.0A18.0 18.0 0 0 1 70.0 29.0Z"), fill = SolidColor(fillColor), stroke = SolidColor(line), strokeLineWidth = 1f, strokeLineCap = StrokeCap.Butt)
        addPath(addPathNodes("M75.0 43.0H245.0A9.0 9.0 0 0 1 254.0 52.0V76.0A9.0 9.0 0 0 1 245.0 85.0H75.0A9.0 9.0 0 0 1 66.0 76.0V52.0A9.0 9.0 0 0 1 75.0 43.0Z"), fill = SolidColor(ground), stroke = SolidColor(line), strokeLineWidth = 1f, strokeLineCap = StrokeCap.Butt)
        addPath(addPathNodes("M75.0 97.0H245.0A9.0 9.0 0 0 1 254.0 106.0V130.0A9.0 9.0 0 0 1 245.0 139.0H75.0A9.0 9.0 0 0 1 66.0 130.0V106.0A9.0 9.0 0 0 1 75.0 97.0Z"), fill = SolidColor(ground), stroke = SolidColor(line), strokeLineWidth = 1f, strokeLineCap = StrokeCap.Butt)
        addPath(addPathNodes("M87.0 64.0A3.0 3.0 0 1 0 81.0 64.0A3.0 3.0 0 1 0 87.0 64.0"), fill = SolidColor(ink), stroke = null, strokeLineWidth = 1f, strokeLineCap = StrokeCap.Butt)
        addPath(addPathNodes("M87.0 118.0A3.0 3.0 0 1 0 81.0 118.0A3.0 3.0 0 1 0 87.0 118.0"), fill = SolidColor(ink), stroke = null, strokeLineWidth = 1f, strokeLineCap = StrokeCap.Butt)
        addPath(addPathNodes("M101 64h67m-67 54h67m49-59v10m8-10v10m8-10v10m-16 44v10m8-10v10m8-10v10"), fill = null, stroke = SolidColor(line), strokeLineWidth = 2f, strokeLineCap = StrokeCap.Round)
        addPath(addPathNodes("M64.0 207.0H86.0A6.0 6.0 0 0 1 92.0 213.0V222.0A6.0 6.0 0 0 1 86.0 228.0H64.0A6.0 6.0 0 0 1 58.0 222.0V213.0A6.0 6.0 0 0 1 64.0 207.0Z"), fill = SolidColor(ground), stroke = SolidColor(line), strokeLineWidth = 1f, strokeLineCap = StrokeCap.Butt)
        addPath(addPathNodes("M234.0 207.0H256.0A6.0 6.0 0 0 1 262.0 213.0V222.0A6.0 6.0 0 0 1 256.0 228.0H234.0A6.0 6.0 0 0 1 228.0 222.0V213.0A6.0 6.0 0 0 1 234.0 207.0Z"), fill = SolidColor(ground), stroke = SolidColor(line), strokeLineWidth = 1f, strokeLineCap = StrokeCap.Butt)
        addPath(addPathNodes("M164.0 190.0A4.0 4.0 0 1 0 156.0 190.0A4.0 4.0 0 1 0 164.0 190.0"), fill = SolidColor(ink), stroke = null, strokeLineWidth = 1f, strokeLineCap = StrokeCap.Butt)
        }.build()
    }
}

val GoogleMark: ImageVector by lazy {
    ImageVector.Builder("Google", 20.dp, 20.dp, 48f, 48f).apply {
        addPath(addPathNodes("M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5Z"), fill = SolidColor(Color(0xFFEA4335)))
        addPath(addPathNodes("M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65Z"), fill = SolidColor(Color(0xFF4285F4)))
        addPath(addPathNodes("M10.53 28.59A14.4 14.4 0 0 1 9.76 24c0-1.59.27-3.13.77-4.59l-7.98-6.19A23.87 23.87 0 0 0 0 24c0 3.87.93 7.52 2.56 10.78l7.97-6.19Z"), fill = SolidColor(Color(0xFFFBBC05)))
        addPath(addPathNodes("M24 48c6.48 0 11.93-2.13 15.91-5.8l-7.73-6c-2.15 1.45-4.92 2.3-8.18 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48Z"), fill = SolidColor(Color(0xFF34A853)))
    }.build()
}
