import { Link } from 'react-router-dom';
import { Compass } from 'lucide-react';
import { EmptyState } from '../components/ui/index.js';
import usePageTitle from '../hooks/usePageTitle.js';

export default function NotFound() {
  usePageTitle('Page not found');
  return (
    <div style={{ minHeight: '70vh', display: 'grid', placeItems: 'center' }}>
      <EmptyState
        icon={Compass}
        title="Page not found"
        message="The page you are looking for does not exist or was moved."
        action={<Link to="/" className="btn btn-primary">Go home</Link>}
      />
    </div>
  );
}
