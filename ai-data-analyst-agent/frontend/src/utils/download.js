import { errorMessage } from '../services/errors.js';

/** Saves a blob response under the server's file name (Content-Disposition), or the fallback. */
export function saveBlob(res, fallbackName) {
  const cd = res.headers['content-disposition'] || '';
  const name = (cd.match(/filename="([^"]+)"/) || [])[1] || fallbackName;
  const href = URL.createObjectURL(res.data);
  const a = document.createElement('a');
  a.href = href;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(href), 2000);
}

export async function blobError(err) {
  // Error bodies of blob requests arrive as Blobs; turn them back into the API's JSON message.
  if (err?.response?.data instanceof Blob) {
    try { err.response.data = JSON.parse(await err.response.data.text()); } catch { /* keep generic */ }
  }
  return errorMessage(err);
}
