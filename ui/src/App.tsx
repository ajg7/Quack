import Composer from "./components/Composer";
import Header from "./components/Header";
import MessageList from "./components/MessageList";

export default function App() {
  return (
    <div className="flex min-h-screen flex-col bg-page">
      <Header />
      <main className="flex flex-1 flex-col">
        <MessageList />
      </main>
      <Composer />
    </div>
  );
}
