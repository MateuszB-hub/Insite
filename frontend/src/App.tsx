import { Routes, Route, Navigate } from 'react-router-dom'
import { AuthProvider } from './auth/AuthContext'
import RequireAuth from './auth/RequireAuth'
import Layout from './components/Layout'
import LoginPage from './pages/LoginPage'
import DashboardPage from './pages/DashboardPage'
import HomePage from './pages/HomePage'
import CareerPathwayPage from './pages/CareerPathwayPage'
import JobSearchPage from './pages/JobSearchPage'
import MyApplicationsPage from './pages/MyApplicationsPage'
import ProfileEditorPage from './pages/ProfileEditorPage'
import ForgotPasswordPage from './pages/ForgotPasswordPage'
import ResetPasswordPage from './pages/ResetPasswordPage'

function App() {
  return (
    <AuthProvider>
      <Routes>
      <Route path="/login" element={<LoginPage />} />
      {/* Public by necessity: a locked-out user cannot authenticate first. */}
      <Route path="/forgot-password" element={<ForgotPasswordPage />} />
      <Route path="/reset-password" element={<ResetPasswordPage />} />
      <Route
        path="/"
        element={
          <RequireAuth>
            <Layout />
          </RequireAuth>
        }
      >
        <Route index element={<Navigate to="/home" replace />} />
        <Route path="home" element={<HomePage />} />
        <Route path="dashboard" element={<DashboardPage />} />
        <Route path="pathway" element={<CareerPathwayPage />} />
        <Route path="jobs" element={<JobSearchPage />} />
        <Route path="applications" element={<MyApplicationsPage />} />
        <Route path="profile" element={<ProfileEditorPage />} />
      </Route>
      </Routes>
    </AuthProvider>
  )
}

export default App
