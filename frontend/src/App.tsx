import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'

import './App.css'
import { Layout } from './Layout'
import { AuthProvider } from './auth/AuthProvider'
import { RequireAuth } from './auth/RequireAuth'
import { Account } from './pages/Account'
import { Schedule } from './pages/Schedule'
import { SignIn } from './pages/SignIn'
import { ThemeProvider } from './theme/ThemeProvider'

function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <ThemeProvider>
          <Routes>
            <Route path="/signin" element={<SignIn />} />
            <Route element={<RequireAuth />}>
              <Route element={<Layout />}>
                <Route path="/" element={<Schedule />} />
                <Route path="/account" element={<Account />} />
              </Route>
            </Route>
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </ThemeProvider>
      </AuthProvider>
    </BrowserRouter>
  )
}

export default App
