#!/usr/bin/env node

import inquirer from 'inquirer';
import chalk from 'chalk';
import { Command } from 'commander';
import boxen from 'boxen';
import { spawn } from 'child_process';
import ora from 'ora';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';
import readline from 'readline';
import { readFileSync } from 'fs';
import Anthropic from '@anthropic-ai/sdk';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

// Read version from package.json
const packageJson = JSON.parse(
  readFileSync(join(__dirname, '../package.json'), 'utf8')
);

const program = new Command();

// Configure the CLI
program
  .name('mellea')
  .description('Mellea Skills Compiler CLI - Agent specification certification pipeline')
  .version(packageJson.version)


// Setup ESC key handler
let escPressed = false;
let currentPrompt = null;
let keypressListenerAttached = false;

// Keypress handler function (defined once)
function handleKeypress(str, key) {
  if (key && key.name === 'escape') {
    escPressed = true;
    console.log('\n');
    console.log(chalk.hex('#F59E0B')('  ⚠️  ESC pressed - Returning to main menu...'));
    console.log();
    // Force close current prompt
    if (currentPrompt) {
      try {
        currentPrompt.ui.close();
      } catch (e) {
        // Ignore close errors
      }
      currentPrompt = null;
    }
    // Small delay to allow cleanup and clear state
    setTimeout(() => {
      escPressed = false;
      runInteractive();
    }, 100);
  }
}

// Configure readline to capture ESC key (only once)
if (process.stdin.isTTY && !keypressListenerAttached) {
  readline.emitKeypressEvents(process.stdin);
  process.stdin.setRawMode(true);
  // Increase the max listeners limit to prevent warnings from inquirer
  process.stdin.setMaxListeners(20);
  process.stdin.on('keypress', handleKeypress);
  keypressListenerAttached = true;
}

// Gradient text helper
function gradient(text, colors) {
  const lines = text.split('\n');
  return lines.map(line => {
    let result = '';
    const step = line.length / (colors.length - 1);
    for (let i = 0; i < line.length; i++) {
      const colorIndex = Math.floor(i / step);
      const color = colors[Math.min(colorIndex, colors.length - 1)];
      result += chalk.hex(color)(line[i]);
    }
    return result;
  }).join('\n');
}

// Stylish title with gradient
function createTitle() {
  const title = '  MELLEA SKILLS COMPILER  ';
  return gradient(title, ['#FF006E', '#8338EC', '#3A86FF', '#06FFA5']);
}

// Display enhanced welcome banner with new design
function showBanner() {
  console.clear();

  const width = 72;

  console.log();

  // Top decorative line
  console.log('  ' + chalk.hex('#00D9FF')('▀'.repeat(width)));

  // Main title with gradient
  console.log();
  const title = '    MELLEA SKILLS COMPILER ver-0.1.0    ';
  const gradientTitle = gradient(title, ['#4ef312']);
  const titlePadding = Math.floor((width - title.length) / 2);
  console.log('  ' + ' '.repeat(titlePadding) + chalk.bold(gradientTitle));
  console.log();

  // Subtitle box
  console.log('  ' + chalk.hex('#00D9FF')('┌' + '─'.repeat(width - 2) + '┐'));

  const wizardText = '🎯 Interactive Wizard Mode';
  const wizardPadding = Math.floor((width - wizardText.length - 2) / 2);
  console.log('  ' + chalk.hex('#00D9FF')('│') + ' '.repeat(wizardPadding) + chalk.hex('#7C3AED').bold(wizardText) + ' '.repeat(width - wizardPadding - wizardText.length - 2) + chalk.hex('#00D9FF')('│'));

  console.log('  ' + chalk.hex('#00D9FF')('├' + '─'.repeat(width - 2) + '┤'));

  const tagline = 'AI Agent Specs  →  Certified Pipelines';
  const taglinePadding = Math.floor((width - tagline.length - 2) / 2);
  console.log('  ' + chalk.hex('#00D9FF')('│') + ' '.repeat(taglinePadding) + chalk.hex('#10B981')(tagline) + ' '.repeat(width - taglinePadding - tagline.length - 2) + chalk.hex('#00D9FF')('│'));

  console.log('  ' + chalk.hex('#00D9FF')('└' + '─'.repeat(width - 2) + '┘'));

  // Bottom decorative line
  console.log('  ' + chalk.hex('#00D9FF')('▄'.repeat(width)));
  console.log();
}

// Show operation header with modern design
function showOperationHeader(operation, icon, description) {
  console.clear();
  console.log();

  const width = 68;
  const topLine = '▄'.repeat(width);
  const bottomLine = '▀'.repeat(width);

  console.log('  ' + chalk.hex('#00D9FF')(topLine));
  console.log();
  console.log('    ' + chalk.hex('#7C3AED').bold(icon + '  ' + operation.toUpperCase()));
  console.log();
  console.log('    ' + chalk.hex('#94A3B8')(description));
  console.log();
  console.log('  ' + chalk.hex('#00D9FF')(bottomLine));
  console.log();
}

// Show command preview with modern styling
function showCommandPreview(args) {
  console.log();
  const width = 66;

  console.log('  ' + chalk.hex('#F59E0B')('  ┌' + '─'.repeat(width) + '┐'));
  console.log('  ' + chalk.hex('#F59E0B')('  │') + chalk.hex('#F59E0B').bold('  ⚡ COMMAND PREVIEW') + ' '.repeat(width - 19) + chalk.hex('#F59E0B')('│'));
  console.log('  ' + chalk.hex('#F59E0B')('  ├' + '─'.repeat(width) + '┤'));
  console.log('  ' + chalk.hex('#F59E0B')('  │') + '  ' + chalk.hex('#10B981')('$') + ' ' + chalk.white('mellea-skills ') + chalk.hex('#00D9FF')(args.join(' ')) + ' '.repeat(Math.max(0, width - args.join(' ').length - 16)) + chalk.hex('#F59E0B')('│'));
  console.log('  ' + chalk.hex('#F59E0B')('  └' + '─'.repeat(width) + '┘'));
  console.log();
}

// Show success with celebration
function showSuccess(operation) {
  console.log();
  const width = 66;

  console.log('  ' + chalk.hex('#10B981')('  ╔' + '═'.repeat(width) + '╗'));
  console.log('  ' + chalk.hex('#10B981')('  ║') + ' '.repeat(width) + chalk.hex('#10B981')('║'));
  console.log('  ' + chalk.hex('#10B981')('  ║') + '         ' + chalk.hex('#10B981').bold('✨  SUCCESS  ✨') + ' '.repeat(width - 24) + chalk.hex('#10B981')('║'));
  console.log('  ' + chalk.hex('#10B981')('  ║') + ' '.repeat(width) + chalk.hex('#10B981')('║'));
  console.log('  ' + chalk.hex('#10B981')('  ║') + '    ' + chalk.white(`${operation} completed successfully!`) + ' '.repeat(Math.max(0, width - operation.length - 28)) + chalk.hex('#10B981')('║'));
  console.log('  ' + chalk.hex('#10B981')('  ║') + ' '.repeat(width) + chalk.hex('#10B981')('║'));
  console.log('  ' + chalk.hex('#10B981')('  ╚' + '═'.repeat(width) + '╝'));
  console.log();
}

// Show error with attention
function showError(operation, error) {
  console.log();
  const width = 66;

  console.log('  ' + chalk.hex('#EC4899')('  ╔' + '═'.repeat(width) + '╗'));
  console.log('  ' + chalk.hex('#EC4899')('  ║') + ' '.repeat(width) + chalk.hex('#EC4899')('║'));
  console.log('  ' + chalk.hex('#EC4899')('  ║') + '         ' + chalk.hex('#EC4899').bold('⚠️  ERROR  ⚠️') + ' '.repeat(width - 22) + chalk.hex('#EC4899')('║'));
  console.log('  ' + chalk.hex('#EC4899')('  ║') + ' '.repeat(width) + chalk.hex('#EC4899')('║'));
  console.log('  ' + chalk.hex('#EC4899')('  ║') + '    ' + chalk.white(`${operation} failed`) + ' '.repeat(Math.max(0, width - operation.length - 11)) + chalk.hex('#EC4899')('║'));
  console.log('  ' + chalk.hex('#EC4899')('  ║') + '    ' + chalk.gray(error.message.substring(0, 60)) + ' '.repeat(Math.max(0, width - Math.min(60, error.message.length) - 4)) + chalk.hex('#EC4899')('║'));
  console.log('  ' + chalk.hex('#EC4899')('  ║') + ' '.repeat(width) + chalk.hex('#EC4899')('║'));
  console.log('  ' + chalk.hex('#EC4899')('  ╚' + '═'.repeat(width) + '╝'));
  console.log();

  next_operation();
}

// Execute Python CLI with beautiful spinner
function executePythonCLI(args, operationName) {
  return new Promise((resolve, reject) => {
    const frames = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏'];
    const spinner = ora({
      text: chalk.hex('#3A86FF').bold(`  ${operationName}`) + chalk.hex('#FFB703')(' in progress...'),
      spinner: { interval: 80, frames },
      color: 'cyan'
    }).start();

    const pythonProcess = spawn('mellea-skills', args, {
      stdio: ['inherit', 'pipe', 'pipe'],
      shell: false
    });

    let outputShown = false;

    pythonProcess.stdout.on('data', (data) => {
      if (!outputShown) {
        spinner.stop();
        console.log();
        outputShown = true;
      }
      process.stdout.write(chalk.white(data.toString()));
    });

    pythonProcess.stderr.on('data', (data) => {
      if (!outputShown) {
        spinner.stop();
        console.log();
        outputShown = true;
      }
      process.stderr.write(chalk.hex('#FF006E')(data.toString()));
    });

    pythonProcess.on('close', (code) => {
      if (code === 0) {
        spinner.succeed(chalk.hex('#06FFA5').bold('  ✨ Complete!'));
        console.log();
        resolve();
      } else {
        spinner.fail(chalk.hex('#FF006E').bold('  ⚠️  Failed!'));
        reject(new Error(`Process exited with code ${code}`));
      }
    });

    pythonProcess.on('error', (error) => {
      spinner.fail(chalk.hex('#FF006E').bold('  ⚠️  Error!'));
      reject(error);
    });
  });
}

// Fetch available Claude models dynamically using Anthropic SDK
async function getAvailableClaudeModels() {
  const spinner = ora({
    text: chalk.hex('#3A86FF')('  Fetching available Claude models...'),
    spinner: { interval: 80, frames: ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏'] },
    color: 'cyan'
  }).start();

  // Fallback models helper
  const getFallbackModels = () => [
    { name: chalk.white('opus'.padEnd(30)) + chalk.hex('#666666')('│ ') + chalk.gray('Most capable'), value: 'opus', short: 'opus' },
    { name: chalk.white('sonnet'.padEnd(30)) + chalk.hex('#666666')('│ ') + chalk.gray('Balanced performance'), value: 'sonnet', short: 'sonnet' },
    { name: chalk.white('haiku'.padEnd(30)) + chalk.hex('#666666')('│ ') + chalk.gray('Fastest response'), value: 'haiku', short: 'haiku' }
  ];

  try {
    const client = new Anthropic();
    const modelsList = await client.models.list();
    const models = modelsList.data.map(model => model.id);

    // Check if models list is empty
    if (!models || models.length === 0) {
      spinner.warn(chalk.hex('#F59E0B')('  No models found, using fallback'));
      console.log();
      return getFallbackModels();
    }

    // Map model IDs to display names with descriptions
    const mappedModels = models.map(modelId => {
      let displayName = modelId;
      let description = '';

      // Parse model ID and create friendly display
      displayName = modelId;
      if (modelId.includes('opus')) {
        description = 'Most capable';
      } else if (modelId.includes('sonnet')) {
        description = 'Balanced performance';
      } else if (modelId.includes('haiku')) {
        description = 'Fastest response';
      }

      return {
        name: chalk.white(displayName.padEnd(30)) + chalk.hex('#666666')('│ ') + chalk.gray(description),
        value: modelId,
        short: displayName
      };
    });

    spinner.succeed(chalk.hex('#06FFA5')(`  Found ${models.length} Claude models`));
    console.log();
    return mappedModels;
  } catch (error) {
    spinner.fail(chalk.hex('#FF006E')('  Failed to fetch Claude models, using fallback'));
    console.log();
    return getFallbackModels();
  }
}

// Get operation details
function getOperationDetails(operation) {
  const details = {
    compile: {
      icon: '🔨',
      name: 'Compile',
      description: 'Transform skill specifications into certified Mellea pipelines',
      color: '#6366F1'
    },
    validate: {
      icon: '✓',
      name: 'Validate',
      description: 'Run structural lints and fixture smoke-checks',
      color: '#14B8A6'
    },
    run: {
      icon: '⚡',
      name: 'Run',
      description: 'Execute compiled skill pipeline with Guardian checks',
      color: '#8B5CF6'
    },
    ingest: {
      icon: '🔒',
      name: 'Ingest',
      description: 'Analyze specifications for risks and generate policies',
      color: '#F97316'
    },
    certify: {
      icon: '🏆',
      name: 'Certify',
      description: 'Comprehensive certification with compliance checks',
      color: '#EF4444'
    },
    export: {
      icon: '📦',
      name: 'Export',
      description: 'Export to deployment targets (LangGraph, Claude Code, MCP)',
      color: '#06B6D4'
    }
  };
  return details[operation];
}

// Store original listener counts to track what we added
const originalExitListeners = process.listenerCount('exit');
const originalSIGINTListeners = process.listenerCount('SIGINT');

// Clean up readline keypress listeners
function cleanupKeypressListeners() {
  if (process.stdin.isTTY) {
    // Get all keypress listeners
    const listeners = process.stdin.listeners('keypress');
    // Remove all but our own handleKeypress listener
    listeners.forEach(listener => {
      if (listener !== handleKeypress) {
        process.stdin.removeListener('keypress', listener);
      }
    });
  }
}

// Clean up process exit listeners added by inquirer
function cleanupProcessListeners() {
  // Get current listeners
  const exitListeners = process.listeners('exit');
  const sigintListeners = process.listeners('SIGINT');

  // Remove excess exit listeners (keep only the original count)
  while (exitListeners.length > originalExitListeners) {
    const listener = exitListeners.pop();
    process.removeListener('exit', listener);
  }

  // Remove excess SIGINT listeners (keep only the original count + our own)
  while (sigintListeners.length > originalSIGINTListeners + 1) {
    const listener = sigintListeners.pop();
    if (listener !== sigintHandler) {
      process.removeListener('SIGINT', listener);
    }
  }
}

async function next_operation() {
  const { again } = await inquirer.prompt([
    {
      type: 'confirm',
      name: 'again',
      message: chalk.hex('#06FFA5').bold('Perform another operation'),
      prefix: chalk.hex('#FFB703')('  🔄'),
      default: true
    }
  ]);

  // Clean up after the final prompt
  cleanupKeypressListeners();
  cleanupProcessListeners();

  if (again) {
    await runInteractive();
  } else {
    console.log();
    const width = 66;
    console.log('  ' + chalk.hex('#06FFA5')('  ╔' + '═'.repeat(width) + '╗'));
    console.log('  ' + chalk.hex('#06FFA5')('  ║') + ' '.repeat(width) + chalk.hex('#06FFA5')('║'));
    console.log('  ' + chalk.hex('#06FFA5')('  ║') + '           ' + chalk.hex('#06FFA5').bold('✨  SESSION COMPLETE  ✨') + ' '.repeat(width - 35) + chalk.hex('#06FFA5')('║'));
    console.log('  ' + chalk.hex('#06FFA5')('  ║') + ' '.repeat(width) + chalk.hex('#06FFA5')('║'));
    console.log('  ' + chalk.hex('#06FFA5')('  ╚' + '═'.repeat(width) + '╝'));
    console.log();
    }
}

// Main interactive flow
async function runInteractive() {
  // Reset all state variables
  escPressed = false;
  currentPrompt = null;

  // Clean up any stale listeners from previous prompts
  cleanupKeypressListeners();
  cleanupProcessListeners();

  showBanner();

  // Show ESC hint
  console.log(chalk.white('  💡 Tip: Press ESC at any time to return to this menu'));
  console.log();

  try {
    console.log(chalk.hex('#7C3AED').bold('  SELECT AN OPERATION'));
    console.log(chalk.hex('#475569')('  ─'.repeat(35)));
    console.log();

    currentPrompt = inquirer.prompt([
      {
        type: 'list',
        name: 'operation',
        message: '',
        prefix: chalk.hex('#00D9FF')('  ▸'),
        pageSize: 15,
        choices: [
          new inquirer.Separator(' '),
          {
            name: chalk.hex('#6366F1')('  🔨  ') + chalk.white.bold('Compile     ') + chalk.hex('#475569')('│ ') + chalk.hex('#ddd6d6')('Transform agent skill specification into certified Mellea pipeline'),
            value: 'compile',
            short: chalk.hex('#6366F1')('Compile')
          },
          new inquirer.Separator(' '),
          {
            name: chalk.hex('#14B8A6')('  ✓   ') + chalk.white.bold('Validate    ') + chalk.hex('#475569')('│ ') + chalk.hex('#ddd6d6')('Run structural lints and smoke-checks on the compiled Mellea pipeline'),
            value: 'validate',
            short: chalk.hex('#14B8A6')('Validate')
          },
          new inquirer.Separator(' '),
          {
            name: chalk.hex('#8B5CF6')('  ⚡  ') + chalk.white.bold('Run         ') + chalk.hex('#475569')('│ ') + chalk.hex('#ddd6d6')('Run compiled Mellea pipeline for the specified fixture and/or with Guardian checks'),
            value: 'run',
            short: chalk.hex('#8B5CF6')('Run')
          },
          new inquirer.Separator(' '),
          {
            name: chalk.hex('#EF4444')('  🏆  ') + chalk.white.bold('Certify     ') + chalk.hex('#475569')('│ ') + chalk.hex('#ddd6d6')('Run compiled Mellea pipeline for comprehensive certification with compliance checks'),
            value: 'certify',
            short: chalk.hex('#EF4444')('Certify')
          },
          new inquirer.Separator(' '),
          {
            name: chalk.hex('#F97316')('  🔒  ') + chalk.white.bold('Ingest      ') + chalk.hex('#475569')('│ ') + chalk.hex('#ddd6d6')('Analyze agent specification for risks and generate policies'),
            value: 'ingest',
            short: chalk.hex('#F97316')('Ingest')
          },
          new inquirer.Separator(' '),
          {
            name: chalk.hex('#06B6D4')('  📦  ') + chalk.white.bold('Export      ') + chalk.hex('#475569')('│ ') + chalk.hex('#ddd6d6')('Export a compiled Mellea pipeline to a deployment target'),
            value: 'export',
            short: chalk.hex('#06B6D4')('Export')
          },
          new inquirer.Separator(' '),
          {
            name: chalk.hex('#EC4899')('  ✕  ') + chalk.white.bold(' Exit        ') + chalk.hex('#475569')('│ ') + chalk.hex('#ddd6d6')('Quit and return to terminal'),
            value: 'exit',
            short: chalk.hex('#EC4899')('Exit')
          }
        ]
      }
    ]);

    const { operation } = await currentPrompt;
    currentPrompt = null;

    // Clean up inquirer's listeners
    cleanupKeypressListeners();
    cleanupProcessListeners();

    // Check if ESC was pressed
    if (escPressed) {
      return;
    }

    if (operation === 'exit') {
      console.log();
      const width = 66;
      console.log('  ' + chalk.hex('#7C3AED')('  ╔' + '═'.repeat(width) + '╗'));
      console.log('  ' + chalk.hex('#7C3AED')('  ║') + ' '.repeat(width) + chalk.hex('#7C3AED')('║'));
      console.log('  ' + chalk.hex('#7C3AED')('  ║') + '                 ' + chalk.hex('#6aed3a').bold('👋  Goodbye!') + ' '.repeat(width - 29) + chalk.hex('#7C3AED')('║'));
      console.log('  ' + chalk.hex('#7C3AED')('  ║') + ' '.repeat(width) + chalk.hex('#7C3AED')('║'));
      console.log('  ' + chalk.hex('#7C3AED')('  ║') + '         ' + chalk.hex('#94A3B8')('Thanks for using Mellea Skills Compiler') + ' '.repeat(width - 48) + chalk.hex('#7C3AED')('║'));
      console.log('  ' + chalk.hex('#7C3AED')('  ║') + ' '.repeat(width) + chalk.hex('#7C3AED')('║'));
      console.log('  ' + chalk.hex('#7C3AED')('  ╚' + '═'.repeat(width) + '╝'));
      console.log();
      process.exit(0);
    }

    const opDetails = getOperationDetails(operation);
    showOperationHeader(opDetails.name, opDetails.icon, opDetails.description);

    let args = [operation];
    let answers;

    // Shared prompt styling
    const promptStyle = {
      prefix: chalk.hex('#06FFA5')('  ▸'),
      transformer: (input, answers, flags) => {
        if (flags.isFinal) {
          return chalk.hex('#06FFA5')(input);
        }
        return chalk.white(input);
      }
    };

    switch (operation) {
      case 'compile':
        // First, get the spec path
        const specPathAnswer = await inquirer.prompt([
          {
            type: 'input',
            name: 'specPath',
            message: chalk.hex('#06FFA5')('Path to skill specification: '),
            prefix: chalk.hex('#06FFA5')('  📄'),
            validate: (input) => input.length > 0 || 'Path required',
            transformer: (input) => chalk.white(input)
          }
        ]);

        console.log();

        // Now fetch available models with loading spinner
        const availableModels = await getAvailableClaudeModels();

        // Continue with remaining prompts
        const remainingAnswers = await inquirer.prompt([
          {
            type: 'list',
            name: 'model',
            message: chalk.hex('#3A86FF')('Select Claude model: '),
            prefix: chalk.hex('#06FFA5')('  🤖'),
            choices: availableModels,
            loop: false,
            transformer: (input) => chalk.white(input)
          },
          {
            type: 'confirm',
            name: 'repairMode',
            message: chalk.hex('#3A86FF')('Enable repair mode: '),
            prefix: chalk.hex('#06FFA5')('  🔧'),
            default: false
          },
          {
            type: 'confirm',
            name: 'skipRun',
            message: chalk.hex('#3A86FF')('Skip post-compile smoke-check: '),
            prefix: chalk.hex('#06FFA5')('  ⚡'),
            default: false
          }
        ]);

        // Combine answers
        answers = { ...specPathAnswer, ...remainingAnswers };

        args.push(answers.specPath);
        if (answers.model) args.push('--model', answers.model);
        if (answers.repairMode) args.push('--repair-mode');
        if (answers.skipRun) args.push('--no-run');
        cleanupKeypressListeners();
        cleanupProcessListeners();
        break;

      case 'validate':
        answers = await inquirer.prompt([
          {
            type: 'input',
            name: 'pipelineDir',
            message: chalk.hex('#06FFA5')('Path to compiled pipeline: '),
            prefix: chalk.hex('#06FFA5')('  📁'),
            validate: (input) => input.length > 0 || 'Path is required',
            transformer: (input) => chalk.white(input)
          },
          {
            type: 'confirm',
            name: 'allFixtures',
            message: chalk.hex('#3A86FF')('Run all fixtures: '),
            prefix: chalk.hex('#06FFA5')('  📋'),
            default: false
          }
        ]);

        args.push(answers.pipelineDir);
        if (answers.allFixtures) args.push('--all');
        cleanupKeypressListeners();
        cleanupProcessListeners();
        break;

      case 'run':
        answers = await inquirer.prompt([
          {
            type: 'input',
            name: 'pipelineDir',
            message: chalk.hex('#FFB703')('Path to compiled pipeline: '),
            prefix: chalk.hex('#06FFA5')('  📁'),
            validate: (input) => input.length > 0 || 'Path is required',
            transformer: (input) => chalk.white(input)
          },
          {
            type: 'input',
            name: 'fixture',
            message: chalk.hex('#3A86FF')('Fixture name: '),
            prefix: chalk.hex('#06FFA5')('  🎯'),
            validate: (input) => input.length > 0 || 'Fixture name is required',
            transformer: (input) => chalk.white(input)
          },
          {
            type: 'confirm',
            name: 'enforce',
            message: chalk.hex('#3A86FF')('Enable enforce mode: '),
            prefix: chalk.hex('#06FFA5')('  🛡️'),
            default: false
          }
        ]);

        args.push(answers.pipelineDir);
        if (answers.fixture) args.push('--fixture', answers.fixture);
        if (answers.enforce) args.push('--enforce');
        cleanupKeypressListeners();
        cleanupProcessListeners();
        break;

      case 'ingest':
        answers = await inquirer.prompt([
          {
            type: 'input',
            name: 'specPath',
            message: chalk.hex('#06FFA5')('Path to agent specification (.md): '),
            prefix: chalk.hex('#06FFA5')('  📄'),
            validate: (input) => input.length > 0 || 'Path is required',
            transformer: (input) => chalk.white(input)
          },
          {
            type: 'confirm',
            name: 'dryRun',
            message: chalk.hex('#3A86FF')('Dry run (preview only): '),
            prefix: chalk.hex('#06FFA5')('  👁️'),
            default: false
          }
        ]);

        args.push(answers.specPath);
        if (answers.dryRun) args.push('--dry-run');
        args.push('--inference-engine', 'ollama');
        cleanupKeypressListeners();
        cleanupProcessListeners();
        break;

      case 'certify':
        answers = await inquirer.prompt([
          {
            type: 'input',
            name: 'pipelineDir',
            message: chalk.hex('#FFB703')('Path to compiled pipeline: '),
            prefix: chalk.hex('#06FFA5')('  📁'),
            validate: (input) => input.length > 0 || 'Path is required',
            transformer: (input) => chalk.white(input)
          },
          {
            type: 'confirm',
            name: 'enforce',
            message: chalk.hex('#3A86FF')('Enable enforce mode: '),
            prefix: chalk.hex('#06FFA5')('  🛡️'),
            default: false
          }
        ]);

        args.push(answers.pipelineDir);
        if (answers.enforce) args.push('--enforce');
        args.push('--inference-engine', 'ollama');
        cleanupKeypressListeners();
        cleanupProcessListeners();
        break;

      case 'export':
        console.log();
        console.log('  ' + chalk.hex('#F59E0B')('  ⚠️  ') + chalk.hex('#F59E0B').bold('Experimental Feature'));
        console.log();

        answers = await inquirer.prompt([
          {
            type: 'input',
            name: 'packagePath',
            message: chalk.hex('#06FFA5')('Path to compiled pipeline: '),
            prefix: chalk.hex('#06FFA5')('  📁'),
            validate: (input) => input.length > 0 || 'Path is required',
            transformer: (input) => chalk.white(input)
          },
          {
            type: 'list',
            name: 'target',
            message: chalk.hex('#3A86FF')('Deployment target: '),
            prefix: chalk.hex('#06FFA5')('  🎯'),
            choices: [
              { name: chalk.white('LangGraph   ') + chalk.hex('#666666')('│ ') + chalk.gray('LangGraph deployment'), value: 'langgraph' },
              { name: chalk.white('Claude Code ') + chalk.hex('#666666')('│ ') + chalk.gray('Claude Code skill'), value: 'claude-code' },
              { name: chalk.white('MCP         ') + chalk.hex('#666666')('│ ') + chalk.gray('Model Context Protocol'), value: 'mcp' }
            ]
          },
          {
            type: 'confirm',
            name: 'force',
            message: chalk.hex('#3A86FF')('Overwrite if exists: '),
            prefix: chalk.hex('#06FFA5')('  💥'),
            default: false
          }
        ]);

        args.push(answers.packagePath);
        args.push('--target', answers.target);
        if (answers.force) args.push('--force');
        cleanupKeypressListeners();
        cleanupProcessListeners();
        break;
    }

    console.log();
    console.log(chalk.hex('#475569')('  ─'.repeat(35)));
    console.log();

    await executePythonCLI(args, opDetails.name);

    next_operation()

  } catch (error) {
    // Handle ESC key interruption
    if (escPressed) {
      return;
    }

    if (error.isTtyError) {
      console.error(chalk.hex('#FF006E')('\n  ⚠️  TTY not supported\n'));
    } else if (error.name === 'ExitPromptError' || error.message.includes('User force closed')) {
      // User interrupted with ESC or Ctrl+C
      return runInteractive();
    } else {
      showError('Operation', error);
    }
    // process.exit(1);
  }
}

// Cleanup on exit (store as named function for reference)
const sigintHandler = () => {
  console.log('\n');
  console.log(chalk.hex('#FFB703')('  👋 Interrupted - Goodbye!'));
  console.log();
  process.exit(0);
};

process.on('SIGINT', sigintHandler);

// Show help if no arguments provided
if (!process.argv.slice(2).length) {
  runInteractive();
} else {
  // Parse command line
  program.parse(process.argv);
}
