import { contextBridge } from "electron";

type ChatResponse = {
  response: string;
  model: string;
};

const backendBaseUrl = process.env.BACKEND_BASE_URL ?? "http://127.0.0.1:8000";

contextBridge.exposeInMainWorld("desktopPetApi", {
  chat: async (message: string): Promise<ChatResponse> => {
    const res = await fetch(`${backendBaseUrl}/chat`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({ message })
    });

    if (!res.ok) {
      const text = await res.text();
      throw new Error(text || `请求失败: ${res.status}`);
    }

    return (await res.json()) as ChatResponse;
  }
});
