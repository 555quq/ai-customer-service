import { createBrowserRouter, RouterProvider } from 'react-router-dom';
import { LoginPage } from './pages/LoginPage';
import { DashboardPage } from './pages/DashboardPage';
import { AgentsPage } from './pages/AgentsPage';
import { ContactsPage } from './pages/ContactsPage';
import { SettingsPage } from './pages/SettingsPage';
import { AIManagementPage } from './pages/AIManagementPage';
import { AuthProvider } from './shared/AuthProvider';
import { ProtectedRoute } from './shared/ProtectedRoute';
import { NotFound } from './shared/NotFound';
import { SetupPage } from './pages/SetupPage';

const router = createBrowserRouter([
  {
    path: '/',
    element: (
      <ProtectedRoute>
        <DashboardPage />
      </ProtectedRoute>
    ),
  },
  {
    path: '/setup',
    element: <SetupPage />,
  },
  {
    path: '/login',
    element: <LoginPage />,
  },
  {
    path: '/dashboard',
    element: (
      <ProtectedRoute>
        <DashboardPage />
      </ProtectedRoute>
    ),
  },
  {
    path: '/agents',
    element: (
      <ProtectedRoute>
        <AgentsPage />
      </ProtectedRoute>
    ),
  },
  {
    path: '/contacts',
    element: (
      <ProtectedRoute>
        <ContactsPage />
      </ProtectedRoute>
    ),
  },
  {
    path: '/settings',
    element: (
      <ProtectedRoute>
        <SettingsPage />
      </ProtectedRoute>
    ),
  },
  {
    path: '/ai',
    element: (
      <ProtectedRoute>
        <AIManagementPage />
      </ProtectedRoute>
    ),
  },
  {
    path: '*',
    element: <NotFound />,
  },
]);

export function RouterApp() {
  return (
    <AuthProvider>
      <RouterProvider router={router} />
    </AuthProvider>
  );
}
