import { Navigate, useLocation } from 'react-router-dom';
import { useAuth } from '../context/AuthContext.jsx';
import { Skeleton } from './ui/index.js';

export default function ProtectedRoute({ children }) {
  const { status } = useAuth();
  const location = useLocation();
  if (status === 'loading') {
    return (
      <div style={{ padding: 32 }} aria-busy="true" aria-label="Loading">
        <Skeleton height={28} width={220} />
        <Skeleton height={140} style={{ marginTop: 16 }} />
      </div>
    );
  }
  if (status !== 'authenticated') {
    return <Navigate to="/signin" replace state={{ from: location.pathname + location.search }} />;
  }
  return children;
}

export function GuestOnly({ children }) {
  const { status } = useAuth();
  if (status === 'authenticated') return <Navigate to="/app" replace />;
  return children;
}
