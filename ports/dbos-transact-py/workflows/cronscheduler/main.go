// Package main schedules a recurring trigger from inside a workflow.
package main

import (
	"fmt"

	"github.com/cleat-team/cleat/cleat"
)

// HandleCronScheduler registers a cron schedule and reports both the id it was
// given and what ListCrons says, so the test can check the two agree.
func HandleCronScheduler(h cleat.HostCalls, targetName string, cronExpr string, markKey string) (string, error) {
	id, err := h.ScheduleCron(targetName, cronExpr, "UTC", fmt.Sprintf(`{"key":%q}`, markKey))
	if err != nil {
		return "", fmt.Errorf("ScheduleCron: %w", err)
	}
	listed, err := h.ListCrons()
	if err != nil {
		return "", fmt.Errorf("ListCrons: %w", err)
	}
	return fmt.Sprintf(`{"scheduleID":%q,"listed":%s}`, id, listed), nil
}
