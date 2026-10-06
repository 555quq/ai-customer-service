import { createBrowserRouter, RouterProvider } from 'react-router-dom';
import { LoginPage } from './pages/LoginPage';
import { WorkspacePage } from './pages/WorkspacePage';
import { ConversationPage } from './pages/ConversationPage';
import { ProfilePage } from './pages/ProfilePage';
import { AuthProvider } from './shared/AuthProvider';
import { ProtectedRoute } from './shared/ProtectedRoute';
import { NotFound } from './shared/NotFound';

const router = createBrowserRouter([
  {
    path: '/',
    element: (
      <ProtectedRoute>
        <WorkspacePage />
      </ProtectedRoute>
    ),
  },
  {
    path: '/login',
    element: <LoginPage />,
  },
  {
    path: '/workspace',
    element: (
      <ProtectedRoute>
        <WorkspacePage />
      </ProtectedRoute>
    ),
  },
  {
    path: '/conversation/:id',
    element: (
      <ProtectedRoute>
        <ConversationPage />
      </ProtectedRoute>
    ),
  },
  {
    path: '/profile',
    element: (
      <ProtectedRoute>
        <ProfilePage />
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