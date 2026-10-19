import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import './index.css'

const container = document.getElementById('root')
if (!container) {
  throw new Error('挂载点 #root 不存在')
}

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
