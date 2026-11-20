/** Предел размера отправляемой картинки: бесплатный OCR.space принимает до 1 МБ, Vercel режет запросы выше 4,5 МБ. */
export const MAX_UPLOAD_BYTES = 950_000
const MAX_SIDE = 2000
const QUALITIES = [0.85, 0.72, 0.6, 0.48, 0.38]

/** Сжимает фото на телефоне до предела (JPEG, сторона до 2000 px). Маленькие файлы идут как есть. */
export async function shrinkImage(file: File): Promise<{ blob: Blob; name: string }> {
  if (file.size <= MAX_UPLOAD_BYTES && (file.type === 'image/jpeg' || file.type === 'image/png')) return { blob: file, name: file.name }
  const bitmap = await createImageBitmap(file)
  let scale = Math.min(1, MAX_SIDE / Math.max(bitmap.width, bitmap.height))
  const name = file.name.replace(/\.[^.]+$/, '') + '.jpg'
  for (let attempt = 0; attempt < 3; attempt += 1) {
    const canvas = document.createElement('canvas')
    canvas.width = Math.max(1, Math.round(bitmap.width * scale))
    canvas.height = Math.max(1, Math.round(bitmap.height * scale))
    canvas.getContext('2d')?.drawImage(bitmap, 0, 0, canvas.width, canvas.height)
    for (const quality of QUALITIES) {
      const blob = await new Promise<Blob | null>((resolve) => { canvas.toBlob(resolve, 'image/jpeg', quality) })
      if (blob && blob.size <= MAX_UPLOAD_BYTES) return { blob, name }
    }
    scale *= 0.7
  }
  throw new Error('image_too_large')
}
