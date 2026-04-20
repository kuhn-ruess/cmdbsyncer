# CMDBsyncer

A rule-based and modular system to synchronize hosts between Checkmk, Netbox, and other systems. The main goal is the complete organization of hosts based on CMDB systems with flexible rules and automation.

## 🔗 Links

* [🌐 Homepage](https://cmdbsyncer.de)
* [📖 Documentation](https://docs.cmdbsyncer.de)

## 📋 Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Quick Start](#quick-start)
- [Supported Systems](#supported-systems)
- [Installation](#installation)
- [Main Functions](#main-functions)
- [Screenshots](#screenshots)
- [Contributing](#contributing)
- [License](#license)

## 🎯 Overview

CMDBsyncer is a powerful, web-based tool designed to solve the complex challenge of managing host inventories across multiple IT management systems. Whether you're synchronizing between Checkmk, Netbox, I-DOIT, or other platforms, CMDBsyncer provides a unified approach with rule-based automation.

### Key Benefits
- **Centralized Management**: Single interface for all your CMDB synchronization needs
- **Rule-Based Logic**: Flexible rules for host organization and attribute management
- **Multi-Platform**: Support for 15+ systems including Checkmk, Netbox, Ansible, and more
- **Scalable**: Tested with 140,000+ hosts
- **Secure**: Built-in authentication, 2FA, and encryption of sensitive data

## ⚡ Quick Start

Get started quickly using Docker Compose:

```bash
# Clone the repository
git clone https://github.com/your-username/cmdbsyncer.git
cd cmdbsyncer

# Start the application
./helper up

# Access the container
./helper shell

# Create your first user
./helper create_user 'your-email@example.com'

# Access the web interface
# Open http://your-host:5003 in your browser
```

This runs a development version that you can use to test everything.

## 📸 Screenshots

![Rules Configuration](https://user-images.githubusercontent.com/899110/201333967-2d7f3f35-cc69-4cad-931f-1da096f94056.png)
*Rule-based synchronization configuration interface*

![Debug Options](https://user-images.githubusercontent.com/899110/201333725-d699d50f-a5eb-4539-a3af-3db3e0647ebb.png)
*Comprehensive debug and testing options*

## 🚀 Main Functions

### Core Features
- **🌐 Web Interface** - Complete web-based management with login, 2FA, and user management
- **⚙️ Configuration Management** - All configuration handled through the web interface (except initial installation)
- **🔌 Plugin API** - Simple API to integrate custom data sources
- **🐛 Debug Tools** - Various debug options available via the `./cmdbsyncer` command
- **🔐 Security** - Encryption of secrets and secure credential management
- **⏰ Scheduling** - Built-in cron management for automated synchronization
- **📊 Monitoring** - Integration with monitoring systems
- **🎯 Template Support** - Jinja2 templating for configuration and rules
- **🔄 REST API** - Full REST API for automation and integration

### Rule Engine
- **📝 Attribute Control** - Rules based on host attributes
- **✏️ Attribute Rewrites** - Dynamic modification of host attributes  
- **🔍 Filters** - Advanced filtering for hosts and attributes
- **⚡ Action Rules** - Automated actions in Ansible, Checkmk, Netbox, etc.

### Ansible Integration
- **📋 Inventory Source** - Use CMDBsyncer as dynamic Ansible inventory

## 🔧 Supported Systems

### Checkmk
**Complete lifecycle management for monitoring systems**

- ✅ **Host Management** - Full host lifecycle (creation, labels, folders, deletion, rules)
- 📈 **Scalability** - Tested with more than 140,000 hosts
- 🏷️ **Attribute Sync** - Sync and update all host attributes, tags, and labels
- ⚡ **Performance** - Full support of API bulk operations and multiprocessing
- 📁 **Folder Management** - Complete Checkmk folder management with pool features
- 👥 **Groups** - Creation of host, contact, and service groups
- 🎯 **Tags** - Create host tags and host tag groups
- 📊 **BI Integration** - Create BI aggregations
- 📋 **Rules** - Create all types of setup rules
- 🔄 **Updates** - Smart update controls to prevent excessive changes
- 🤖 **Agents** - Commands to activate configuration, bake and sign agents
- 👤 **User Management** - Manage Checkmk users (create/delete/reset password)
- 📦 **Inventory** - Host attributes inventory for Ansible integration
- 🔐 **Password Store** - Create and manage encrypted password entries
- 🎯 **DCD Rules** - Create Data Collection Rules
- 🔍 **Version Detection** - Automatic Checkmk version detection for correct API usage

### Ansible
**Automation and configuration management**

- 📋 **Inventory** - Rule-based inventory source
- 🖥️ **Agent Management** - Complete Checkmk agent management (Linux & Windows)
  - Installation and TLS registration
  - Bakery registration
- 🏗️ **Site Management** - OMD site management (updates, creation)
  - Automatic Checkmk version downloads

### Netbox
**Network infrastructure management**

- 🔄 **Bidirectional Sync** - Rule-based export and import of devices and VMs
- 🏗️ **Auto-Creation** - Automatic category creation
- 🗺️ **Infrastructure** - Export sites, interfaces, IPAM data
- 👥 **Contacts** - Contact management
- 📍 **Location Management** - Comprehensive location handling

### I-DOIT
**IT documentation and CMDB**

- 📊 **Template-Based** - Rule-based export and import using templates
- 🔄 **Bidirectional** - Full import/export capabilities

### Other Integrations

#### **PRTG** - Network monitoring
- 📥 **Object Import** - Import monitoring objects to sync with Checkmk

#### **BMC Remedy** - IT Service Management  
- 📊 **Limited Import** - Basic import functionality

#### **Cisco DNA** - Network management
- 🌐 **Device Import** - Import devices and interface information

#### **CSV Files** - Data management
- 📄 **Host Management** - Manage hosts based on CSV files
- ➕ **Data Enhancement** - Add additional information from CSV files

#### **LDAP** - Directory services
- 👥 **Object Import** - Import objects from LDAP directories

#### **REST APIs** - Custom integrations
- 🔌 **Custom APIs** - Import from custom REST API endpoints

#### **JSON** - File-based data
- 📄 **File Import** - Import JSON file structures

#### **Jira CMDB** - Atlassian integration
- ☁️ **Cloud & On-Prem** - Support for both deployment types
- 📥 **Object Import** - Import CMDB objects

#### **JDISC** - Network discovery
- 🔍 **Discovery Import** - Import discovered objects

#### **VMware** - Virtualization
- 📊 **Attribute Management** - Import and export VM attributes
- 🔄 **Bidirectional** - Full import/export to VMware VMs

#### **Database Systems**
- **MySQL** - Import and inventory database tables
- **MSSQL/FreeTDS/ODBC** - Support for all ODBC-based database connections

## 🛠️ Installation

### Prerequisites
- Docker and Docker Compose
- Python 3.11+ (for development)
- Web browser (for the management interface)

### Production Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/your-username/cmdbsyncer.git
   cd cmdbsyncer
   ```

2. **Configure environment**
   ```bash
   # Copy and edit configuration files
   cp docker-compose.prod.yml docker-compose.yml
   # Edit the configuration as needed
   ```

3. **Start the application**
   ```bash
   docker-compose up -d
   ```

4. **Create admin user**
   ```bash
   ./helper create_user 'admin@your-domain.com'
   ```

### Development Installation

For development and testing purposes:

```bash
# Start development environment
./helper up

# Access container shell
./helper shell

# Create test user  
./helper create_user 'test@example.com'

# Access at http://localhost:5003
```

## 📋 Requirements

### System Requirements
- **Memory**: Minimum 2GB RAM, recommended 4GB+
- **Storage**: Minimum 10GB free space
- **Network**: HTTPS access to target systems (Checkmk, Netbox, etc.)

### Supported Target Systems
- **Checkmk**: All current versions (automatic detection)
- **Netbox**: v2.8+ 
- **Ansible**: v2.9+
- **I-DOIT**: v1.12+
- **And many more** - see [full compatibility matrix](https://docs.cmdbsyncer.de)

## 🤝 Contributing

We welcome contributions! Please follow these steps:

1. **Fork the repository**
2. **Create a feature branch** (`git checkout -b feature/amazing-feature`)
3. **Commit your changes** (`git commit -m 'Add amazing feature'`)
4. **Push to the branch** (`git push origin feature/amazing-feature`)
5. **Open a Pull Request**

### Development Guidelines
- Follow existing code style
- Add tests for new features
- Update documentation as needed
- Test with multiple target systems

### Git Hooks

The repository ships a `pre-commit` hook in `.githooks/` that refreshes
`application/buildinfo.txt`, runs pylint on staged Python files, and executes
the unit-test suite before each commit. Activate it once per clone:

```bash
git config core.hooksPath .githooks
```

## 📄 License

This project is licensed under the [MIT License](LICENSE) - see the LICENSE file for details.

## 🆘 Support

- 📖 **Documentation**: [docs.cmdbsyncer.de](https://docs.cmdbsyncer.de)
- 🌐 **Homepage**: [cmdbsyncer.de](https://cmdbsyncer.de)  
- 🐛 **Issues**: [GitHub Issues](https://github.com/kuhn-ruess/cmdbsyncer/issues)
- 💬 **Discussions**: [GitHub Discussions](https://github.com/kuhn-ruess/cmdbsyncer/discussions)

---

⭐ **If you find this project helpful, please give it a star!** ⭐
