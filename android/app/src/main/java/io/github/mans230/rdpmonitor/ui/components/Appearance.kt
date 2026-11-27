package io.github.mans230.rdpmonitor.ui.components

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.os.Build
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Image
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.border
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.blur
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.layout.positionInRoot
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.IntSize
import io.github.mans230.rdpmonitor.ui.theme.*
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

private val LocalAppearance = staticCompositionLocalOf<(() -> Unit)?> { null }
private data class Backdrop(val bitmap: Bitmap? = null, val rootSize: IntSize = IntSize.Zero, val shade: Float = .85f)
private val LocalBackdrop = staticCompositionLocalOf { Backdrop() }
@Composable fun appearanceAction(): () -> Unit = LocalAppearance.current ?: {}

/** Session-only, bounded local image. Nothing is saved to a profile or uploaded. */
@Composable fun AppearanceShell(content: @Composable () -> Unit) {
    var bitmap by remember { mutableStateOf<Bitmap?>(null) }
    var motionReview by remember { mutableStateOf(false) }
    var dialog by rememberSaveable { mutableStateOf(false) }
    var blur by rememberSaveable { mutableFloatStateOf(24f) }
    var shade by rememberSaveable { mutableFloatStateOf(.85f) }
    var error by remember { mutableStateOf<String?>(null) }
    var loading by remember { mutableStateOf(false) }
    var rootSize by remember { mutableStateOf(IntSize.Zero) }
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val picker = rememberLauncherForActivityResult(ActivityResultContracts.GetContent()) { uri ->
        if (uri != null) scope.launch {
            loading = true; error = null
            val result = withContext(Dispatchers.IO) { runCatching {
                require(context.contentResolver.getType(uri) in setOf("image/jpeg", "image/png", "image/webp")) { "Choose a JPG, PNG or WebP image." }
                val data = context.contentResolver.openInputStream(uri)?.use { input ->
                    val output = java.io.ByteArrayOutputStream()
                    val buffer = ByteArray(8192)
                    while (true) {
                        val count = input.read(buffer)
                        if (count < 0) break
                        require(output.size() + count <= 15 * 1024 * 1024) { "Choose an image under 15 MB." }
                        output.write(buffer, 0, count)
                    }
                    output.toByteArray()
                }
                    ?: error("Could not open this image.")
                require(data.size <= 15 * 1024 * 1024) { "Choose an image under 15 MB." }
                val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
                BitmapFactory.decodeByteArray(data, 0, data.size, bounds)
                require(bounds.outWidth > 0 && bounds.outHeight > 0) { "This image could not be decoded." }
                var sample = 1
                while (bounds.outWidth / sample > 1600 || bounds.outHeight / sample > 1600) sample *= 2
                BitmapFactory.decodeByteArray(data, 0, data.size, BitmapFactory.Options().apply { inSampleSize = sample })
                    ?: error("This image could not be decoded.")
            } }
            result.onSuccess { bitmap = it }.onFailure { error = it.message ?: "Could not open this image." }
            loading = false
        }
    }
    CompositionLocalProvider(LocalAppearance provides { dialog = true }, LocalMotionPreview provides { motionReview = true }, LocalBackdrop provides Backdrop(bitmap, rootSize, shade)) {
        Box(Modifier.fillMaxSize().onGloballyPositioned { rootSize = it.size }.background(Ground)) {
            bitmap?.let { image ->
                // Blur the image layer only. Older Android uses a stronger opaque fallback.
                Image(image.asImageBitmap(), null, Modifier.matchParentSize().then(if (Build.VERSION.SDK_INT >= 31) Modifier.blur(blur.dp) else Modifier), contentScale = ContentScale.Crop)
                Box(Modifier.matchParentSize().background(Ground.copy(alpha = if (Build.VERSION.SDK_INT >= 31) shade else maxOf(.92f, shade))))
            }
            content()
        }
        if (io.github.mans230.rdpmonitor.BuildConfig.DEBUG && motionReview) CossDialog(onDismissRequest = { motionReview = false }, title = { Text("Motion previews") },
            text = { Column(verticalArrangement = Arrangement.spacedBy(16.dp)) { MotionPreviewContent() } },
            confirmButton = { CossOutlinedButton(onClick = { motionReview = false }, modifier = Modifier.fillMaxWidth()) { Text("Done") } })
        if (dialog) CossDialog(onDismissRequest = { dialog = false }, title = { Text("Appearance") }, text = {
            Column(verticalArrangement = Arrangement.spacedBy(16.dp)) {
                if (io.github.mans230.rdpmonitor.BuildConfig.DEBUG) CossOutlinedButton(onClick = { dialog = false; motionReview = true }) { Text("Motion previews") }
                Text("Optional local background. It stays on this device for this session and is never uploaded.")
                CossOutlinedButton(onClick = { picker.launch("image/*") }, enabled = !loading) { Text(if (loading) "Opening image…" else "Choose background image") }
                Text("Background blur · ${blur.toInt()}")
                Slider(blur, { blur = it }, valueRange = 0f..40f, enabled = bitmap != null && Build.VERSION.SDK_INT >= 31)
                Text("Background overlay · ${(shade * 100).toInt()}%")
                Slider(shade, { shade = it }, valueRange = .70f.. .95f, enabled = bitmap != null)
                if (Build.VERSION.SDK_INT < 31) Text("This Android version uses a stronger dark overlay instead of blur.", color = Muted)
                error?.let { Notice(it, true) }
                CossTextButton(onClick = { bitmap = null; error = null }, enabled = bitmap != null) { Text("Remove background") }
            }
        }, confirmButton = { CossTextButton(onClick = { dialog = false }) { Text("Done") } })
    }
}

/** Repaint only the matching wallpaper region and blur that layer, never foreground content. */
@Composable fun GlassSurface(modifier: Modifier = Modifier, radius: Dp = 14.dp, blur: Dp = 18.dp, content: @Composable () -> Unit) {
    val backdrop = LocalBackdrop.current
    val shape = RoundedCornerShape(radius)
    var position by remember { mutableStateOf(Offset.Zero) }
    Box(modifier.onGloballyPositioned { position = it.positionInRoot() }.clip(shape)
        .background(Panel.copy(alpha = if (Build.VERSION.SDK_INT >= 31) .82f else .94f))
        .border(1.dp, Signal.copy(alpha = .14f), shape)) {
        val bitmap = backdrop.bitmap
        if (bitmap != null && Build.VERSION.SDK_INT >= 31 && backdrop.rootSize.width > 0) {
            val image = remember(bitmap) { bitmap.asImageBitmap() }
            Canvas(Modifier.matchParentSize().blur(blur)) {
                val scale = maxOf(backdrop.rootSize.width.toFloat() / image.width, backdrop.rootSize.height.toFloat() / image.height)
                val width = (image.width * scale).toInt(); val height = (image.height * scale).toInt()
                drawImage(image, dstOffset = IntOffset(((backdrop.rootSize.width - width) / 2f - position.x).toInt(), ((backdrop.rootSize.height - height) / 2f - position.y).toInt()), dstSize = IntSize(width, height))
            }
            Box(Modifier.matchParentSize().background(Ground.copy(alpha = .76f)))
        }
        Box(Modifier.matchParentSize().background(Color.White.copy(alpha = .025f)))
        content()
    }
}
