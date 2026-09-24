import { BrowserRouter, Route, Routes } from "react-router";

export function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="*" element={<main className="p-6 font-mono">Owner</main>} />
      </Routes>
    </BrowserRouter>
  );
}
