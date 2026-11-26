package io.github.mans230.rdpmonitor.ui.components

import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.graphics.vector.addPathNodes
import androidx.compose.ui.unit.dp

/** Lucide outline paths from the approved coss reference; see LUCIDE-LICENSE.txt. */
object CossIcons {
    private fun vector(name: String, paths: List<String>, strokeWidth: Float = 2f) = ImageVector.Builder(name, 24.dp, 24.dp, 24f, 24f).apply {
        paths.forEach { addPath(addPathNodes(it), fill = null, stroke = SolidColor(Color.Black), strokeLineWidth = strokeWidth, strokeLineCap = StrokeCap.Round, strokeLineJoin = StrokeJoin.Round) }
    }.build()
    val FileArchive by lazy { vector("file-archive", listOf("M13.659 22H18a2 2 0 0 0 2-2V8a2.4 2.4 0 0 0-.706-1.706l-3.588-3.588A2.4 2.4 0 0 0 14 2H6a2 2 0 0 0-2 2v11.5", "M14 2v5a1 1 0 0 0 1 1h5", "M8 12v-1", "M8 18v-2", "M8 7V6", "M 10.0 20.0 A 2.0 2.0 0 1 0 6.0 20.0 A 2.0 2.0 0 1 0 10.0 20.0")) }
    val Folder by lazy { vector("folder", listOf("M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z")) }
    val Archive by lazy { vector("archive", listOf("M2.0 3.0H22.0V8.0H2.0Z", "M4 8v11a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8", "M10 12h4")) }
    val ArrowRight by lazy { vector("arrow-right", listOf("M5 12h14", "m12 5 7 7-7 7")) }
    val Clock by lazy { vector("clock", listOf("M 22.0 12.0 A 10.0 10.0 0 1 0 2.0 12.0 A 10.0 10.0 0 1 0 22.0 12.0", "M12 6v6l4 2")) }
    val ListFilter by lazy { vector("list-filter", listOf("M2 5h20", "M6 12h12", "M9 19h6")) }
    val Activity by lazy { vector("activity", listOf("M22 12h-2.48a2 2 0 0 0-1.93 1.46l-2.35 8.36a.25.25 0 0 1-.48 0L9.24 2.18a.25.25 0 0 0-.48 0l-2.35 8.36A2 2 0 0 1 4.49 12H2")) }
    val Server by lazy { vector("server", listOf("M4 2H20A2 2 0 0 1 22 4V8A2 2 0 0 1 20 10H4A2 2 0 0 1 2 8V4A2 2 0 0 1 4 2Z", "M4 14H20A2 2 0 0 1 22 16V20A2 2 0 0 1 20 22H4A2 2 0 0 1 2 20V16A2 2 0 0 1 4 14Z", "M6 6h.01M6 18h.01")) }
    val ServerThin by lazy { vector("server", listOf("M4 2H20A2 2 0 0 1 22 4V8A2 2 0 0 1 20 10H4A2 2 0 0 1 2 8V4A2 2 0 0 1 4 2Z", "M4 14H20A2 2 0 0 1 22 16V20A2 2 0 0 1 20 22H4A2 2 0 0 1 2 20V16A2 2 0 0 1 4 14Z", "M6 6h.01M6 18h.01"), 1.4f) }
    val X by lazy { vector("x", listOf("M18 6 6 18", "m6 6 12 12")) }
}
