import { Outlet } from 'react-router-dom'
import Sidebar from './Sidebar'
import Header from './Header'

export default function Layout() {
  return (
    <div className="min-h-screen flex">
      <Sidebar />
      <div className="flex-1 flex flex-col">
        <Header />
        <main className="flex-1 p-6 overflow-auto scrollbar-thin">
          <div className="max-w-7xl mx-auto animate-in">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  )
}
