import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { ClaimDetail } from './pages/ClaimDetail'
import { ClaimsList } from './pages/ClaimsList'

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<ClaimsList />} />
        <Route path="/claims/:id" element={<ClaimDetail />} />
      </Routes>
    </BrowserRouter>
  )
}

export default App
