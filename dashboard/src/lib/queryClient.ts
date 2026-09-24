import { QueryClient } from '@tanstack/react-query'
import { ApiError } from '../api/client'

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: (failureCount, error) => error instanceof ApiError && error.status >= 400 && error.status < 500
        ? false
        : failureCount < 2,
    },
  },
})
