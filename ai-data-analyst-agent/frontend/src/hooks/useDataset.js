import { useCallback, useEffect, useRef, useState } from 'react';
import api from '../services/api.js';
import { errorMessage } from '../services/errors.js';

const BUSY = new Set(['pending', 'running']);

/** Loads a dataset and polls while cleaning runs. */
export default function useDataset(id, { pollMs = 1200 } = {}) {
  const [dataset, setDataset] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(Boolean(id));
  const timer = useRef(null);

  const load = useCallback(async () => {
    if (!id) return null;
    try {
      const { data } = await api.get(`/datasets/${id}`);
      setDataset(data);
      setError(null);
      return data;
    } catch (err) {
      setError(errorMessage(err));
      return null;
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    setDataset(null);
    setLoading(Boolean(id));
    load();
    return () => clearTimeout(timer.current);
  }, [id, load]);

  useEffect(() => {
    clearTimeout(timer.current);
    if (dataset && BUSY.has(dataset.cleaning_status)) {
      timer.current = setTimeout(load, pollMs);
    }
    return () => clearTimeout(timer.current);
  }, [dataset, load, pollMs]);

  return { dataset, error, loading, reload: load, busy: dataset ? BUSY.has(dataset.cleaning_status) : false };
}

export const STATUS_TONE = { done: 'success', running: 'info', pending: 'info', failed: 'danger' };
export const STATUS_LABEL = { done: 'Cleaned', running: 'Cleaning', pending: 'Queued', failed: 'Failed' };
