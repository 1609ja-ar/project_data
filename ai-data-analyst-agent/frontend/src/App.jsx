import { lazy, Suspense } from 'react';
import { Route, Routes } from 'react-router-dom';
import ProtectedRoute, { GuestOnly } from './components/ProtectedRoute.jsx';
import { Card, Skeleton } from './components/ui/index.js';

const Landing = lazy(() => import('./pages/Landing.jsx'));
const SignIn = lazy(() => import('./pages/SignIn.jsx'));
const SignUp = lazy(() => import('./pages/SignUp.jsx'));
const ForgotPassword = lazy(() => import('./pages/ForgotPassword.jsx'));
const ResetPassword = lazy(() => import('./pages/ResetPassword.jsx'));
const NotFound = lazy(() => import('./pages/NotFound.jsx'));
const AppLayout = lazy(() => import('./layouts/AppLayout.jsx'));
const Overview = lazy(() => import('./pages/app/Overview.jsx'));
const Settings = lazy(() => import('./pages/app/Settings.jsx'));
const Upload = lazy(() => import('./pages/app/Upload.jsx'));
const Datasets = lazy(() => import('./pages/app/Datasets.jsx'));
const DatasetDetail = lazy(() => import('./pages/app/DatasetDetail.jsx'));
const SqlWorkbench = lazy(() => import('./pages/app/SqlWorkbench.jsx'));
const Exports = lazy(() => import('./pages/app/Exports.jsx'));
const CleanData = lazy(() => import('./pages/app/CleanData.jsx'));
const Pivot = lazy(() => import('./pages/app/Pivot.jsx'));
const Insights = lazy(() => import('./pages/app/Insights.jsx'));
const Dashboard = lazy(() => import('./pages/app/Dashboard.jsx'));
const Reports = lazy(() => import('./pages/app/Reports.jsx'));
const ReportView = lazy(() => import('./pages/app/ReportView.jsx'));
const Ask = lazy(() => import('./pages/app/Ask.jsx'));
const SharedDashboard = lazy(() => import('./pages/SharedDashboard.jsx'));

function PageFallback() {
  return (
    <div style={{ padding: 24 }} aria-busy="true" aria-label="Loading page">
      <Skeleton height={28} width={240} />
      <Skeleton height={16} width={360} style={{ marginTop: 10 }} />
      <Card pad style={{ marginTop: 24 }}><Skeleton height={220} /></Card>
    </div>
  );
}

const page = (el) => <Suspense fallback={<PageFallback />}>{el}</Suspense>;

export default function App() {
  return (
    <Suspense fallback={<PageFallback />}>
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/signin" element={<GuestOnly><SignIn /></GuestOnly>} />
        <Route path="/signup" element={<GuestOnly><SignUp /></GuestOnly>} />
        <Route path="/s/:token" element={<SharedDashboard />} />
        <Route path="/forgot-password" element={<ForgotPassword />} />
        <Route path="/reset-password" element={<ResetPassword />} />
        <Route path="/app" element={<ProtectedRoute><AppLayout /></ProtectedRoute>}>
          <Route index element={page(<Overview />)} />
          <Route path="dashboard" element={page(<Dashboard />)} />
          <Route path="ask" element={page(<Ask />)} />
          <Route path="reports" element={page(<Reports />)} />
          <Route path="reports/:id" element={page(<ReportView />)} />
          <Route path="upload" element={page(<Upload />)} />
          <Route path="datasets" element={page(<Datasets />)} />
          <Route path="datasets/:id" element={page(<DatasetDetail />)} />
          <Route path="sql" element={page(<SqlWorkbench />)} />
          <Route path="exports" element={page(<Exports />)} />
          <Route path="downloads" element={page(<CleanData />)} />
          <Route path="pivot" element={page(<Pivot />)} />
          <Route path="insights" element={page(<Insights />)} />
          <Route path="settings" element={page(<Settings />)} />
          <Route path="*" element={page(<NotFound />)} />
        </Route>
        <Route path="*" element={<NotFound />} />
      </Routes>
    </Suspense>
  );
}
